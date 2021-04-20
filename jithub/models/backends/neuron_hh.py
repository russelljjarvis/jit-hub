import io
import math
import pdb
import timeit
from quantities import mV, ms, s, V
import sciunit
from neo import AnalogSignal
import neuronunit.capabilities as cap
import numpy as np
from .base import *
import quantities as qt
from quantities import mV, ms, s, V
import matplotlib as mpl

# try:
#    import asciiplotlib as apl
# except:
#    pass
import numpy

voltage_units = mV

from sciunit.utils import redirect_stdout

from elephant.spike_train_generation import threshold_detection
from neuronunit.optimisation.model_parameters import path_params
import time


from numba import jit
import numpy as np

# @jit(nopython=True)
@jit
def inner_core(fPots, vIndex, vTime, fTime, duration, vTimes, vPots, fDt, iter_):
    for time in iter_:
        if fTime == vTime:
            fPots.append(vPots[vIndex])

        # Interpolate between the two nearest vdt times
        else:

            # Increment vdt time until it surpases the fdt time
            while fTime > vTime and vIndex < len(vTimes):
                vIndex += 1
                vTime = vTimes[vIndex]

            # Once surpassed, use the new vdt time and t-1
            # for interpolation
            vIndexMinus1 = max(0, vIndex - 1)
            vTimeMinus1 = vTimes[vIndexMinus1]

            # def linearInterpolate(tStart, tEnd, vStart, vEnd, tTarget):
            tStart, tEnd, vStart, vEnd, tTarget = (
                vTimeMinus1,
                vTime,
                vPots[vIndexMinus1],
                vPots[vIndex],
                fTime,
            )
            tRange = tEnd - tStart
            tFractionAlong = (tTarget - tStart) / tRange
            vRange = vEnd - vStart
            fPot = vRange * tFractionAlong + vStart

            fPots.append(fPot)

        # Go to the next fdt time step
        fTime += fDt
    return fPots


@jit
def get_fixed_step_analog_signal(
    desired_fixedTimeStep, varied_Pots, varied_Times
):  # ,iterator):
    """Convert variable dt array values to fixed dt array.

    Uses linear interpolation.
    """
    # Fixed dt potential
    fPots = []
    fDt = desired_fixedTimeStep
    # Variable dt potential
    vPots = varied_Pots
    # self.vVector.to_python()
    # Variable dt times
    vTimes = varied_Times  # self.tVector.to_python()
    duration = vTimes[len(vTimes) - 1]
    # Fixed and Variable dt times
    fTime = vTimes[0]
    vTime = vTimes[0]
    # Index of variable dt time array
    vIndex = 0
    # Advance the fixed dt position
    #
    iter_ = range(0, int(duration / fDt) - 1)
    fPots = inner_core(
        fPots,
        int(vIndex),
        float(vTime),
        float(fTime),
        float(duration),
        list(vTimes),
        list(vPots),
        float(fDt),
        iter_,
    )
    return fPots, iter_


@jit
def get_int(tvec):
    list_of_intervals = []
    for i, t in enumerate(tvec):
        if i > 0:
            list_of_intervals.append(t - tvec[i - 1])
    return np.min(list_of_intervals)


class NEURONHHBackend(Backend):
    """Use for simulation with NEURON, a popular simulator.

    http://www.neuron.yale.edu/neuron/
    Units used by NEURON are sometimes different to quantities/neo
    (note nA versus pA)
    http://neurosimlab.org/ramcd/pyhelp/modelspec/programmatic/mechanisms/mech.html#IClamp
    NEURON's units:
    del -- ms
    dur -- ms
    amp -- nA
    i -- nA
    """

    name = "NEURONHH"

    def init_backend(self, attrs=None, DTC=None):
        """Initialize the NEURON backend for neuronunit.

        Arguments should be consistent with an underlying model files.

        Args:
            attrs (dict): a dictionary of items used to update NEURON
                          model attributes.
            cell_name (string): A string that represents the cell models name
                                in the NEURON HOC space.
            current_src_name (string): A string that represents the current
                                       source models name in the NEURON HOC
                                       space.
            DTC (DataTransportContainer): The data transport container contain
                                          a dictionary of model attributes
                                          When the DTC object is provided,
                                          it's attribute dictionary can be used
                                          to update the NEURONBackends model
                                          attribute dictionary.
        """
        if not NEURON_SUPPORT:
            msg = "The neuron module was not successfully imported"
            raise BackendException(msg)

        self.stdout = io.StringIO()
        self.neuron = None
        self.model_path = None
        self.h = h
        self.h.load_file("stdlib.hoc")

        self.h.load_file("stdgui.hoc")
        self.default_attrs = {
            "gnabar": 0.12,
            "gkbar": 0.036,
            "Ra": 100,
            "L": 12.6157,
            "diam": 12.6157,
            "gkbar": 0.036,
            "el": -54.3,
            "gl": 0.0003,
            "ena": 50.0,
            "ek": -77.0,
            "vr": -65,
            "cm": 1.0,
            "ena": 50.0,
            "ek": -77,
        }
        super(NEURONHHBackend, self).init_backend()
        self.model._backend.use_memory_cache = False
        self.model.unpicklable += ["h", "ns", "_backend"]
        self.load_model()
        if type(DTC) is not type(None):
            if type(DTC.attrs) is not type(None):

                self.set_attrs(DTC.attrs)
                if len(DTC.attrs):
                    assert len(self.model.attrs) > 0

            if hasattr(DTC, "current_src_name"):
                self._current_src_name = DTC.current_src_name

            if hasattr(DTC, "cell_name"):
                self._cell_name = DTC.cell_name

    def reset_neuron(self, neuronVar):
        """Reset the neuron simulation.

        Refreshes the the HOC module, purging it's variable namespace.
        Sets the NEURON h variable, and resets the NEURON h variable.
        The NEURON h variable, may benefit from being reset between simulation
        runs as a way of insuring that each simulation is freshly initialized.
        the reset_neuron method is used to prevent a situation where a new
        model's initial conditions are erroneously updated from a stale model's
        final state.

        Args:
            neuronVar (module): a reference to the neuron module
        """
        self.h = neuronVar.h
        self.neuron = neuronVar
        # h = neuron.h
        # self.h.load_file("stdlib.hoc")
        # self.h.load_file("stdgui.hoc")
        self.load_model()

    def set_run_params(self, **run_params):
        pass

    def set_stop_time(self, stop_time=1200 * pq.ms):
        """Set the simulation duration
        stopTimeMs: duration in milliseconds
        """
        self.h.tstop = float(stop_time.rescale(pq.ms))

    def get_spike_count(self):
        thresh = threshold_detection(self.vM, threshold=0.0 * pq.mV, sign=above)
        return len(thresh)

    '''
    def set_time_step(self, integrationTimeStep=(pq.ms/128.0)):
        """Set the simulation itegration fixed time step
        integrationTimeStepMs: time step in milliseconds.
        Powers of two preferred. Defaults to 1/128.0

        Args:
            integrationTimeStep (float): time step in milliseconds.
                Powers of two preferred. Defaults to 1/128.0
        """
        dt = integrationTimeStep
        self.h.dt = 0.1#float(dt)0.01
    '''
    '''
    def set_tolerance(self, tolerance=0.001):
        """Set the variable time step integration method absolute tolerance.

        Args:
            tolerance (float): absolute tolerance value
        """
        self.h.cvode.atol(tolerance)
    '''

    def set_integration_method(self, method="variable"):
        """Set the simulation itegration method.

        cvode is used when method is "variable"

        Args:
            method (string): either "fixed" or "variable". Defaults to fixed.
        """

        # This line is compatible with the above cvodes statements.
        self.h.cvode.active(1 if method == "variable" else 0)

        try:
            assert self.h.cvode.active()
        except AssertionError:
            self.h.cvode = self.h.CVode()
            self.h.cvode.active(1 if method == "variable" else 0)

    '''
    def get_variable_step_analog_signal(self):
        """Convert variable dt array values to fixed dt array.

        Uses linear interpolation.
        """
        # Fixed dt potential
        fPots = []
        fDt = self.fixedTimeStep
        # Variable dt potential
        vPots = self.vVector.to_python()
        # Variable dt times
        vTimes = self.tVector.to_python()
        duration = vTimes[len(vTimes)-1]
        # Fixed and Variable dt times
        fTime = vTime = vTimes[0]
        # Index of variable dt time array
        vIndex = 0
        # Advance the fixed dt position
        while fTime <= duration:

            # If v and f times are exact, no interpolation needed
            if fTime == vTime:
                fPots.append(vPots[vIndex])

            # Interpolate between the two nearest vdt times
            else:

                # Increment vdt time until it surpases the fdt time
                while fTime > vTime and vIndex < len(vTimes):
                    vIndex += 1
                    vTime = vTimes[vIndex]

                # Once surpassed, use the new vdt time and t-1
                # for interpolation
                vIndexMinus1 = max(0, vIndex-1)
                vTimeMinus1 = vTimes[vIndexMinus1]

                fPot = self.linearInterpolate(vTimeMinus1, vTime,
                                              vPots[vIndexMinus1],
                                              vPots[vIndex], fTime)

                fPots.append(fPot)

            # Go to the next fdt time step
            fTime += fDt

        return fPots
    '''

    def get_membrane_potential(self):
        """Get a membrane potential traces from the simulation.

        Must destroy the hoc vectors that comprise it.

        Returns:
            neo.core.AnalogSignal: the membrane potential trace
        """
        """

        #if self.h.cvode.active() == 0:
        dt = float(self.h.dt)
        fixed_signal = self.vVector.to_python()
        #else:
            #dt = float(self.fixedTimeStep)
        #    dt = self.h.dt
        #    self.fixedTimeStep = float(dt)

            #fixed_signal = self.get_variable_step_analog_signal()

        #self.h.dt = dt
        fixed_signal = [ v for v in fixed_signal ]
        self.vM = AnalogSignal(fixed_signal,
                            units=pq.mV,
                            sampling_period=self.h.dt*pq.ms)
        """

        return self.vM  # waves0 = [i.rescale(qt.mV) for i in waves0 ]

    '''
    def linearInterpolate(self, tStart, tEnd, vStart, vEnd, tTarget):
        """Perform linear interpolation."""
        tRange = float(tEnd - tStart)
        tFractionAlong = (tTarget - tStart)/tRange
        vRange = vEnd - vStart
        vTarget = vRange*tFractionAlong + vStart

        return vTarget

    def load(self, tstop=650*pq.ms):
        #nrn_path = (os.path.splitext(self.model.orig_lems_file_path)[0] +
        #            '_nrn.py')
        #nrn = import_module_from_path(nrn_path)

        self.reset_neuron(nrn.neuron)
        self.h.tstop = tstop
        self.set_stop_time(tstop)  # previously 500ms add on 150ms of recovery
        #with redirect_stdout(self.stdout):
        self.ns = nrn.NeuronSimulation(self.h.tstop, dt=0.1)

    def load_mechanisms(self):
        with redirect_stdout(self.stdout):
            neuron.load_mechanisms(self.neuron_model_dir)
    '''

    def load_model(self, verbose=True):
        """Load a NEURON model.

        Side Effects: Substantially mutates neuronal model stored in self.
        Description: Take a declarative model description, and call JneuroML
        to convert it into an python/neuron implementation stored in a pyho
        file. Then import the pyhoc file thus dragging the neuron variables
        into memory/python name space. Since this only happens once outside
        of the optimization loop its a tolerable performance hit.

        Create a pyhoc file using jneuroml to convert from NeuroML to pyhoc.
        import the contents of the file into the current names space.
        """

        soma = h.Section(name="soma")
        soma.nseg = 1
        soma.insert("hh")
        soma.insert("pas")
        self.soma = soma
        return self

    def set_attrs(self, attrs):
        # make sure all attributes are acoounted for.
        # if assingment is incomplete assume user does not want to explicitly specify
        # everything and is satisfied by defaults.
        self.default_attrs.update(attrs)
        attrs = self.default_attrs

        if not hasattr(self.model, "attrs"):  # is None:
            self.model.attrs = {}
            self.model.attrs.update(attrs)
        else:
            self.model.attrs.update(attrs)

        self.soma(0.5).hh.gl = attrs["gl"]
        self.soma(0.5).hh.gnabar = attrs["gnabar"]
        self.soma(0.5).hh.gkbar = attrs["gkbar"]
        self.soma(0.5).cm = attrs["cm"]
        self.soma.L = attrs["L"]

        self.soma.diam = attrs["diam"]  # 12.6157 # Makes a soma of 500 microns squared.

        for sec in self.h.allsec():
            sec.Ra = attrs["Ra"]  # Axial resistance in Ohm * cm
            sec.cm = attrs["cm"]  # Membrane capacitance in micro Farads / cm^2
        # import pdb; pdb.set_trace()
        self.soma(0.5).hh.el = attrs["el"]
        # self.soma(0.5).k_ion.ek = attrs['ek']
        # self.soma(0.5).na_ion.ena = attrs['ena']

        self.vVector = self.h.Vector()  # Membrane potential vector
        self.tVector = self.h.Vector()  # Time stamp vector
        self.vVector.record(self.soma(0.5)._ref_v)
        self.tVector.record(self.h._ref_t)
        return self

    def inject_square_current(self, current, section=None, debug=False):

        """Apply current injection into the soma or a specific compartment.

        Example: current = {'amplitude':float*pq.pA, 'delay':float*pq.ms,
                            'duration':float*pq.ms}}
        where 'pq' is a physical unit representation, implemented by casting
        float values to the quanitities 'type'.
        Currently only single section neuronal models are supported, the
        neurite section is understood to be simply the soma.

        Args:
            current (dict): a dictionary with exactly three items,
              whose keys are: 'amplitude', 'delay', 'duration'

        Implementation:
        1. purge the HOC space, by calling reset_neuron()
        2. Redefine the neuronal model in the HOC namespace, which was recently
           cleared out.
        3. Strip away quantities representation of physical units.
        4. Translate the dictionary of current injection parameters into
           executable HOC code.
        """
        try:
            assert len(self.model.attrs)
        except:
            print(
                "this means you didnt instance a model and then add in model parameters"
            )
        temp_attrs = self.model.attrs
        assert len(temp_attrs)

        self.init_backend()
        self.h.cvode.active(1)
        # self.set_integration_method(method="variable")
        if len(temp_attrs):
            self.set_attrs(temp_attrs)

        current = current
        self.last_current = current
        if "injected_square_current" in current.keys():
            c = current["injected_square_current"]
        else:
            c = current

        ##
        # critical code:
        ##
        stop_time = (
            float(c["delay"]) * pq.ms + float(c["duration"]) * pq.ms + 200.0 * pq.ms
        )
        # translate pico amps to nano amps
        # NEURONs default unit multiplier for current injection values is nano amps.
        # to make sure that pico amps are not erroneously interpreted as a larger nano amp.
        # current injection value, the value is divided by 1000.
        stim = self.h.IClamp(self.soma(0.5))
        amp = (
            float(c["amplitude"]) / 1000.0
        )  # *1000.0#.rescale('nA'))#/1000.0#*1000.0*1000.0#*1000.0#.rescale('nA'))#*1000.0#*1.0/1000.0#.rescale('nA'))
        # print(amp)
        # amp = amp*0.001#1000.0 # convert back to nano amps
        # assert amp!=-0.0
        # print(amp)
        dur = float(c["duration"])  # .rescale('ms'))
        delay = float(c["delay"])  # .rescale('ms'))
        stim.amp = amp
        stim.dur = dur
        stim.delay = delay

        # simdur = dur+delay #2000.0
        tMax = delay + dur + 200.0
        self.h.tstop = tMax
        # b4 = time.perf_counter()
        self.h.dt = 1
        self.set_stop_time(stop_time)

        with redirect_stdout(self.stdout):
            self.h("run()")  # +str(tMax)+')')
        # af = time.perf_counter()
        # print('time:',af - b4)
        tvec = [float(x) for x in self.tVector]
        # print(tvec[1],self.h.dt)
        # get_int(tvec)
        vm = [float(x) for x in self.vVector]
        vm_fast, vm_times = get_fixed_step_analog_signal(tvec[1], vm, tvec)
        """
        self.vM = AnalogSignal(vm,
                                units=pq.mV,
                                sampling_period=tvec[1]*pq.ms)
        t = [float(f) for f in self.vM.times]
        v = [float(f) for f in self.vM.magnitude]
        v_fast = [float(f) for f in self.vM_other]
        t_fast = [float(f) for f in self.vM_other.times]
        fig = apl.figure()
        fig.plot(t, v, width=100, height=20)
        fig.plot(t_fast, v_fast, width=100, height=20)
        fig.show()
        """
        self.vM = AnalogSignal(vm_fast, units=pq.mV, sampling_period=tvec[1] * pq.ms)

        is_nan_in_vm = False
        for v in self.vM:
            if np.isnan(float(v)):
                is_nan_in_vm = True
                # print('gets to nan')
        # if is_nan_in_vm:
        #    print(self.attrs)
        return self.vM

    def local_run(self):
        # with redirect_stdout(self.stdout):
        self.h("run()")
        results = {}
        results["vm"] = AnalogSignal(
            [float(x) for x in self.vVector],
            units=pq.mV,
            sampling_period=self.h.dt * pq.ms,
        )
        results["t"] = results["vm"].times

        results["run_number"] = results.get("run_number", 0) + 1

        return results

    def _backend_run(self):
        self.inject_square_current(self.last_current)
        return self.local_run()
