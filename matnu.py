# -*- coding: utf-8 -*-
# -*- mode: python -*-
""" Python reference implementations of model code
CODE ORIGINALLY FROM
https://github.com/melizalab/mat-neuron/blob/master/mat_neuron/_pymodel.py

"""

from __future__ import division, print_function, absolute_import

from quantities import mV, ms, s, V
from neo import AnalogSignal
import neuronunit.capabilities as cap
import numpy as np
import quantities as pq
import numpy
voltage_units = mV
import copy
from elephant.spike_train_generation import threshold_detection

#from mat_neuron.core import impulse_matrix
import numba
from numba import jit#, autojit
import cython

from numpy import exp
#from scipy import pow
from scipy import linalg
import time
def timer(func):
    def inner(*args, **kwargs):
        t1 = time.time()
        f = func(*args, **kwargs)
        t2 = time.time()
        print('time taken on block {0} '.format(t2-t1))
        return f
    return inner
dt = 1.0
class MATModel():

    name = 'MAT'

    def __init__(self, attrs=None):
        self.vM = None
        self.attrs = attrs
        self.temp_attrs = None
        #params = [10, 2, 0, 5, 10, 10, 10, 200, 5, 2]

        self.default_attrs = {'vr':-65.0,'vt':-55.0,'a1':10, 'a2':2, 'b':0, 'w':5, 'R':10, 'tm':10, 't1':10, 't2':200, 'tv':5, 'tref':2}

        if type(attrs) is not type(None):
            self.attrs = attrs
        if self.attrs is None:
            self.attrs = self.default_attrs


    def get_spike_count(self):
        #thresh = threshold_detection(self.vM,0*qt.mV)
        return len(self.spikes)


    def set_stop_time(self, stop_time = 650*pq.ms):
        """Sets the simulation duration
        stopTimeMs: duration in milliseconds
        """
        self.tstop = float(stop_time.rescale(pq.ms))

    def set_attrs(self, attrs):
        self.attrs = attrs

    #self.default_attrs = {'vr':-65.0,'vt':-55.0,'a1':10, 'a2':2, 'b':0, 'w':5,
    # 'R':10, 'tm':10, 't1':10,
    # 't2':200, 'tv':5, 'tref':2}

    #@jit
    def impulse_matrix_direct(self,a1=10.0, a2=2.0, b=0, w=5,
                               tm=10,t1=10, t2=200, tv=5, tref=2,R=10):

        Aexp = np.zeros((6, 6), dtype='d')
        #a1, a2, b, w, _, tm, t1, t2, tv, tref = self.attrs['a1'],self.attrs['a2'],self.attrs['b'],self.attrs['w'], self.attrs['R'], self.attrs['tm'], self.attrs['t1'], self.attrs['t2'], self.attrs['tv'], self.attrs['tref']
        Aexp[0, 0] = exp(-dt / tm)
        Aexp[0, 1] = tm - tm * exp(-dt / tm)
        Aexp[1, 1] = 1.
        Aexp[2, 2] = exp(-dt / t1)
        Aexp[3, 3] = exp(-dt / t2)
        Aexp[4, 0] = b*tv*(dt*tm*exp(dt/tm) - dt*tv*exp(dt/tm) + \
                                              tm*tv*exp(dt/tm) - \
                                              tm*tv*exp(dt/tv))*exp(-dt/tv - dt/tm)/(pow(tm, 2) - \
                                              2*tm*tv + pow(tv, 2))
        Aexp[4, 1] = b*tm*tv*(-dt*(tm - tv)*exp(dt*(tm + tv)/(tm*tv)) + \
                     tm*tv*exp(2*dt/tv) - \
                     tm*tv*exp(dt*(tm + tv)/(tm*tv)))*exp(-dt*(2*tm + tv)/(tm*tv))/pow(tm - tv, 2)
        Aexp[4, 4] = exp(-dt / tv)
        Aexp[4, 5] = dt * exp(-dt / tv)
        Aexp[5, 0] = b*tv*exp(-dt/tv)/(tm - tv) - b*tv*exp(-dt/tm)/(tm - tv)
        Aexp[5, 1] = -b*tm*tv*exp(-dt/tv)/(tm - tv) + b*tm*tv*exp(-dt/tm)/(tm - tv)
        Aexp[5, 5] = exp(-dt / tv)
        return Aexp

    #@jit
    @timer
    def impulse_matrix(self,a1=10.0, a2=2.0, b=0.0, w=5.0,
                               tm=10.0,t1=10.0, t2=200.0, tv=5.0, tref=2.0,R=10.0,dt = 1.0):
        """Calculate the matrix exponential for integration of MAT model"""
        #_, _, b, w, _, tm, t1, t2, tv, tref = self.attrs['a1'],self.attrs['a2'],self.attrs['b'],self.attrs['w'], self.attrs['R'], self.attrs['tm'], self.attrs['t1'], self.attrs['t2'], self.attrs['tv'], self.attrs['tref']

        #if not reduced:
        A = - np.matrix([[1.0 / tm, -1., 0., 0., 0., 0.],
                         [0., 0., 0., 0., 0., 0.],
                         [0., 0., 1. / t1, 0., 0., 0.],
                         [0., 0., 0., 1. / t2, 0., 0.],
                         [0., 0., 0., 0., 1. / tv, -1.],
                         [b / tm, -b, 0., 0., 0., 1. / tv]])
        '''
        else:
         	A = - np.matrix([[1 / tm, -1, 0, 0],
                             [0,       0, 0, 0],
                             [0, 0, 1 / tv, -1],
                             [b / tm, -b, 0, 1 / tv]])
        '''
        return linalg.expm(A * dt)

    @jit
    def predict(self, current, dt):
        """Integrate model to predict spiking response
        This method uses the exact integration method
        of Rotter and Diesmann (1999).
        Note that this implementation implicitly
        represents the driving current as a
        series of pulses, which may or may not be appropriate.
        parameters: 9-element sequence (α1, α2, β, ω, τm, R, τ1, τ2, and τV)
        state: 5-element sequence (V, θ1, θ2, θV, ddθV)
        [all zeros works fine]
        current: a 1-D array of N current values
        dt: time step of forcing current, in ms
        Returns an Nx5 array of the model state variables and a list of spike times
        """
        D = 6
        a1, a2, b, w, R, tm, t1, t2, tv, tref = self.attrs['a1'],self.attrs['a2'],self.attrs['b'],self.attrs['w'], self.attrs['R'], self.attrs['tm'], self.attrs['t1'], self.attrs['t2'], self.attrs['tv'], self.attrs['tref']
        params = [a1, a2, b, w, R, tm, t1, t2, tv, tref]
        v, phi, h1, h2, x, d = self.state
        Aexp = impulse_matrix(params, dt)
        N = current.size
        Y = np.zeros((N, D))
        y = np.asarray(self.state)
        spikes = []
        iref = 0
        last_I = 0
        for i in range(N):
            y = -65+np.dot(Aexp, y)
            print(y)
            y[1] += R / tm * (current[i] - last_I)
            last_I = current[i]
            # check for spike
            h = y[2] + y[3] + y[4] + w
            if i > iref and y[0] > h:
                y[2] += a1
                y[3] += a2
                iref = i + int(tref * dt)
                spikes.append(i * dt)
            #Y[i] = y
            Y[i] = (y-3.0)/30.0

        self.state = y
        self.vM = AnalogSignal(Y,
                units=pq.V,
                sampling_period=1*pq.ms)
        return self.vM, spikes

    #@jit
    #@timer
    def inject_square_current(self, current):
        """Integrate just the current-dependent variables.
        This function is usually called as a first step when evaluating the
        log-likelihood of a spike train. Usually there are several trials for each
        stimulus, so it's more efficient to predict the voltage and its derivative
        from the current separately.
        See predict() for specification of params and state arguments
        """

        #I = np.zeros(1000, dtype='d')
        if 'delay' in current.keys() and 'duration' in current.keys():
            square = True
            c = current
        if isinstance(c['amplitude'],type(pq)):
            amplitude = float(c['amplitude'].simplified)
            duration = float(c['duration'])#.simplified)
            delay = float(c['delay'])#.simplified)
        else:
            amplitude = float(c['amplitude'])
            duration = float(c['duration'])
            delay = float(c['delay'])
        tMax = delay + duration
        tMax = self.tstop = float(tMax)
        N = int(tMax/1)
        current = np.zeros(N)
        delay_ind = int((delay/tMax)*N)
        duration_ind = int((duration/tMax)*N)
        current[0:delay_ind-1] = 0.0
        current[delay_ind:delay_ind+duration_ind-1] = amplitude
        current[delay_ind+duration_ind::] = 0.0
        D = 6
        #a1, a2, b, w, R, tm, t1, t2, tv, tref = self.attrs['a1'],self.attrs['a2'],self.attrs['b'],self.attrs['w'], self.attrs['R'], self.attrs['tm'], self.attrs['t1'], self.attrs['t2'], self.attrs['tv'], self.attrs['tref']
        dt = 1.0
        #params = [a1, a2, b, w, R, tm, t1, t2, tv, tref]
        Aexp = self.impulse_matrix(a1=self.attrs['a1'],
                                          a2=self.attrs['a2'],
                                          b=self.attrs['b'],
                                          w=self.attrs['w'],
                                          tm=self.attrs['tm'],
                                          t1=self.attrs['t1'],
                                          t2=self.attrs['t2'],
                                          tv=self.attrs['tv'],
                                          tref=self.attrs['tref'],
                                          R=self.attrs['R'])
        #Aexp = self.impulse_matrix(reduced=False)
        #state: 5-element sequence (V, θ1, θ2, θV, ddθV)
        #state: 5-element sequence (V, θ1, θ2, θV, ddθV)

        v, phi, h1, h2, x, d = [0,0,0,0,0,0]
        #(V, I, θV, ddθV)
        y = np.asarray([v, phi, h1, h2, x, d], dtype='d')

        #v, phi, h1, h2, , d = self.state

        #v, phi, _, _, , d = [self.attrs['vr'],self.attrs['vt'],0,0,0,0]
        #self.state = v, phi, _, _, , d
        '''
        N = current.size
        Y = np.zeros((N, D), dtype='d')
        x = np.zeros(D, dtype='d')
        last_I = 0.0
        vm = np.zeros(N, dtype='d')

        for i in range(N):
            x[1] = R / tm * (current[i] - last_I)
            last_I = current[i]
            y = np.dot(Aexp, y) + x
            #print(y,np.shape(y))
            Y[i] = y
            vm[i] = y[0]
        self.state = y
        '''
        N = current.size
        Y = np.zeros((N, D))
        #y = np.asarray([v, phi, h1, h2,x , d], dtype='d')

        #y = np.asarray(self.state)
        spikes = []
        iref = 0
        last_I = 0
        vm = np.zeros(N, dtype='d')

        for i in range(N):
            #y = np.dot(Aexp, y)
            y = np.dot(Aexp, y)
            #print(y)

            y[1] += R / tm * (current[i] - last_I)
            last_I = current[i]
            # check for spike
            h = y[2] + y[3] + y[4] + w
            if i > iref and y[0] > h:
                y[2] += a1
                y[3] += a2
                iref = i + int(tref * dt)
                spikes.append(i * dt)
            Y[i] = (y-3.0)/30.0
            #vm[i] = y[0]

        self.state = y
        self.spikes = spikes

        self.vM = AnalogSignal([np.sum(y) for y in Y],
                            units=pq.V,
                            sampling_period=1*pq.ms)

        #self.vM = AnalogSignal([0.005*(np.sum(y))-0.07 for y in Y],
        #                    units=pq.V,
        #                    sampling_period=1*pq.ms)
        #print(len(spikes))
        #(V, I, θV, ddθV)
        return self.vM

        #return Y

    @jit
    def predict_adaptation(params, spikes, dt, N):
        """Predict the voltage-independent adaptation variables from known spike times.
        This function is usually called as a second step when evaluating the
        log-likelihood of a spike train.
        See predict() for specification of params and state arguments
        """
        D = 2
        a1, a2, b, w, R, tm, t1, t2, tv, tref = self.attrs['a1'],self.attrs['a2'],self.attrs['b'],self.attrs['w'], self.attrs['R'], self.attrs['tm'], self.attrs['t1'], self.attrs['t2'], self.attrs['tv'], self.attrs['tref']
        _, h1, h2, _, _ = self.state
        # the system matrix is purely diagonal, so these are exact solutions
        A1 = np.exp(-dt / t1)
        A2 = np.exp(-dt / t2)
        y = np.asarray([h1, h2], dtype='d')
        Y = np.zeros((N, D), dtype='d')
        idx = (np.asarray(spikes) / dt).astype('i')
        spk = np.zeros(N)
        spk[idx] = 1
        for i in range(N):
            y[0] = A1 * y[0] + a1 * spk[i]
            y[1] = A2 * y[1] + a2 * spk[i]
            Y[i] = y
        return Y

    @jit
    def log_intensity(V, H, params):
        """Evaluate the log likelihood of spiking with an exponential link function.
        V: 2D array with voltage and θV in the first two columns
        H: 2D array with θ1 and θ2 in the first two columns
        params: list of parameters (see predict() for specification)
        """
        return V[:, 0] - H[:, 0] - H[:, 1] - V[:, 1] - params[3]
