#from .base import BaseModel
from .backends.izhikevich import JIT_IZHIBackend
from .backends.mat_nu import JIT_MATBackend
from .backends.adexp import JIT_ADEXPBackend

from copy import copy
import collections
import quantities as pq
from sciunit import capabilities as scap
from neuronunit import capabilities as ncap

from bluepyopt.ephys.models import CellModel
from neuronunit.models.optimization_model_layer import OptimizationModel

class BPOModel(CellModel,ncap.ReceivesSquareCurrent,ncap.ProducesMembranePotential,scap.Runnable):
    def __init__(self,name,attrs={}):
        self.mechanisms = None
        self.morphology = None
        self.name = "neuronunit_numba_model"
        self.attrs = attrs
        self.jithub = True
    def get_backend(self):
        return self.backend

    def get_AP_widths(self):
        from neuronunit.capabilities import spike_functions as sf
        vm = self.get_membrane_potential()
        widths = sf.spikes2widths(vm)
        return widths

    def freeze(self, param_dict):
        """
        Over ride parent class method
        Set params

        """

        for param_name, param_value in param_dict.items():
            if hasattr(self.params[param_name],'freeze'):# is type(np.float):
                self.params[param_name].freeze(param_value)
            else:
                from bluepyopt.parameters import Parameter

                self.params[param_name] = Parameter(name=param_name,value=param_value,frozen=True)


    def instantiate(self, sim=None):
        """
        Over ride parent class method
        Instantiate model in simulator
        As if called from a genetic algorithm.
        """
        if self.params is not None:
            self.attrs = self.params

        dtc = self.model_to_dtc()
        for k,v in self.params.items():
            if hasattr(v,'value'):
                v = float(v.value)

            dtc.attrs[k] = v
            self.attrs[k] = v
        return dtc


    def model_to_dtc(self,attrs=None):
        """
        Args:
            self
        Returns:
            dtc
            DTC is a simulator indipendent data transport container object.
        """


        dtc = OptimizationModel(backend=self.backend)
        dtc.attrs = self.attrs
        return dtc

        if type(attrs) is not type(None):
            if len(attrs):
                dtc.attrs = attrs
                self.attrs = attrs
            assert self._backend is not None
            return dtc
        else:
            if type(self.attrs) is not type(None):
                if len(self.attrs):
                    try:
                        dynamic_attrs = {str(k):float(v) for k,v in self.attrs.items()}
                    except:
                        dynamic_attrs = {str(k):float(v.value) for k,v in self.attrs.items()}

        if self._backend is None:
            super(VeryReducedModel, self).__init__(name=self.name,backend=self.backend)#,attrs=dtc.attrs)
            assert self._backend is not None
        frozen_attrs = self._backend.default_attrs
        if 'dynamic_attrs' in locals():
            frozen_attrs.update(dynamic_attrs)
        all_attrs = frozen_attrs
        dtc.attrs = all_attrs
        assert dtc.attrs is not None
        return dtc


    def check_nonfrozen_params(self, param_names):
        """
        Over ride parent class method
        Check if all nonfrozen params are set"""
        for param_name, param in self.params.items():
            if not param.frozen:
                raise Exception(
                    'CellModel: Nonfrozen param %s needs to be '
                    'set before simulation' %
                    param_name)


from sciunit.models import RunnableModel
class ADEXPModel(JIT_ADEXPBackend,BPOModel,OptimizationModel,RunnableModel):
    def __init__(self, name="not_None", params=None):
        self.default_attrs = {}
        self.default_attrs['cm']=0.281
        self.default_attrs['v_spike']=-40.0
        self.default_attrs['v_reset']=-70.6
        self.default_attrs['v_rest']=-70.6
        self.default_attrs['tau_m']=9.3667
        self.default_attrs['a']=4.0
        self.default_attrs['b']=0.0805
        self.default_attrs['delta_T']=2.0
        self.default_attrs['tau_w']=144.0
        self.default_attrs['v_thresh']=-50.4
        self.default_attrs['spike_delta']=30

        if params is not None:
            self.params = collections.OrderedDict(**params)
        else:
            self.params = self.default_attrs
        self._attrs = self.params
        BPOModel.__init__(self,name)
        OptimizationModel.__init__(self,attrs=self.params,backend=self)
        RunnableModel._backend = JIT_ADEXPBackend
        self.morphology = None
        RunnableModel.morphology = None
        RunnableModel.mechanisms = None
        self.ampl = 0
        self._attrs = self.params

class IzhiModel(JIT_IZHIBackend,BPOModel,OptimizationModel,RunnableModel):
    def __init__(self, name=None, params=None, backend=JIT_IZHIBackend):
        self.default_attrs = {'C':89.7960714285714,
                              'a':0.01, 'b':15, 'c':-60, 'd':10, 'k':1.6,
                              'vPeak':(86.364525297619-65.2261863636364),
                              'vr':-65.2261863636364, 'vt':-50, 'celltype':3}
        if params is not None:
            self.params = collections.OrderedDict(**params)
        else:
            self.params = self.default_attrs
        BPOModel.__init__(self,name)
        OptimizationModel.__init__(self,attrs=self.params,backend=self)
        RunnableModel._backend = JIT_IZHIBackend
        self.morphology = None
        RunnableModel.morphology = None
        RunnableModel.mechanisms = None



class MATModel(BPOModel):
    def __init__(self, name=None, attrs=None, backend=JIT_MATBackend):
        self.default_attrs = {'vr':-65.0,'vt':-55.0,'a1':10, 'a2':2, 'b':0, 'w':5, 'R':10, 'tm':10, 't1':10, 't2':200, 'tv':5, 'tref':2}
        if attrs is None:
            attrs = {}
        attrs_ = copy(self.default_attrs)
        for key, value in attrs:
            attrs_[key] = value
        super().__init__(name=name, attrs=attrs_, backend=backend)
