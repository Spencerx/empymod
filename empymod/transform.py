"""

:mod:`transform` -- Hankel and Fourier Transforms
=================================================

Methods to carry out the required Hankel transform from wavenumber to
frequency domain and Fourier transform from frequency to time domain.

The functions for the QWE and FHT Hankel and Fourier transforms are based on
source files (specified in each function) from the source code distributed with
[Key_2012]_, which can be found at `software.seg.org/2012/0003
<http://software.seg.org/2012/0003>`_. These functions are (c) 2012 by Kerry
Key and the Society of Exploration Geophysicists,
http://software.seg.org/disclaimer.txt. Please read the NOTICE-file in the root
directory for more information regarding the involved licenses.

"""
# Copyright 2016-2017 Dieter Werthmüller
#
# This file is part of `empymod`.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License.  You may obtain a copy
# of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.  See the
# License for the specific language governing permissions and limitations under
# the License.


import numpy as np
from scipy import special, fftpack, integrate
from scipy.interpolate import InterpolatedUnivariateSpline as iuSpline

from . import kernel

__all__ = ['fht', 'hqwe', 'hquad', 'ffht', 'fqwe', 'fftlog', 'fft', 'qwe',
           'get_spline_values', 'fhti']


# 1. Hankel transforms (wavenumber -> frequency)


def fht(zsrc, zrec, lsrc, lrec, off, angle, depth, ab, etaH, etaV, zetaH,
        zetaV, xdirect, fhtarg, use_spline, use_ne_eval, msrc, mrec):
    """Hankel Transform using the Fast Hankel Transform.

    The *Fast Hankel Transform* is a *Digital Filter Method*, introduced to
    geophysics by [Gosh_1971]_, and made popular and wide-spread by
    [Anderson_1975]_, [Anderson_1979]_, [Anderson_1982]_.

    This implementation of the FHT follows [Key_2012]_, equation 6.  Without
    going into the mathematical details (which can be found in any of the above
    papers) and following [Key_2012]_, the FHT method rewrites the Hankel
    transform of the form

    .. math:: F(r)   = \int^\infty_0 f(\lambda)J_v(\lambda r)\
            \mathrm{d}\lambda

    as

    .. math::   F(r)   = \sum^n_{i=1} f(b_i/r)h_i/r \ ,

    where :math:`h` is the digital filter.The Filter abscissae b is given by

    .. math:: b_i = \lambda_ir = e^{ai}, \qquad i = -l, -l+1, \cdots, l \ ,

    with :math:`l=(n-1)/2`, and :math:`a` is the spacing coefficient.

    This function is loosely based on `get_CSEM1D_FD_FHT.m` from the source
    code distributed with [Key_2012]_.

    The function is called from one of the modelling routines in :mod:`model`.
    Consult these modelling routines for a description of the input and output
    parameters.

    Returns
    -------
    fEM : array
        Returns frequency-domain EM response.

    kcount : int
        Kernel count. For FHT, this is 1.

    conv : bool
        Only relevant for QWE/QUAD.

    """
    # Get fhtargs
    fhtfilt = fhtarg[0]
    pts_per_dec = fhtarg[1]

    # For FHT, spline for one offset is equals no spline
    if use_spline and off.size == 1:
        use_spline = False

    # 1. COMPUTE REQUIRED LAMBDAS for given hankel-filter-base
    if use_spline:           # Use interpolation
        # Get lambda from offset and filter
        lambd, ioff = get_spline_values(fhtfilt, off, pts_per_dec)

    else:  # df.base/off
        lambd = fhtfilt.base/off[:, None]

    # 2. CALL THE KERNEL
    PJ0, PJ1, PJ0b = kernel.wavenumber(zsrc, zrec, lsrc, lrec, depth, etaH,
                                       etaV, zetaH, zetaV, lambd, ab, xdirect,
                                       msrc, mrec, use_ne_eval)

    if use_spline and pts_per_dec:  # If spline in wnr-domain, interpolate PJ's
        # Interpolate in wavenumber domain
        PJ0real = iuSpline(np.log10(lambd), PJ0.real)
        PJ0imag = iuSpline(np.log10(lambd), PJ0.imag)
        PJ1real = iuSpline(np.log10(lambd), PJ1.real)
        PJ1imag = iuSpline(np.log10(lambd), PJ1.imag)
        PJ0breal = iuSpline(np.log10(lambd), PJ0b.real)
        PJ0bimag = iuSpline(np.log10(lambd), PJ0b.imag)

        # Overwrite lambd with non-spline lambd
        lambd = fhtfilt.base/off[:, None]

        # Get fEM-field at required non-spline lambdas
        PJ0 = PJ0real(np.log10(lambd)) + 1j*PJ0imag(np.log10(lambd))
        PJ1 = PJ1real(np.log10(lambd)) + 1j*PJ1imag(np.log10(lambd))
        PJ0b = PJ0breal(np.log10(lambd)) + 1j*PJ0bimag(np.log10(lambd))

        # Set spline to false
        use_spline = False

    elif use_spline:  # If spline in frequency domain, re-arrange PJ's
        def rearrange_PJ(PJ, noff, nfilt):
            """Return re-arranged PJ with shape (noff, nlambd).
               Each row starts one 'lambda' higher."""
            outarr = np.concatenate((np.tile(PJ, noff).squeeze(),
                                    np.zeros(noff)))
            return outarr.reshape(noff, -1)[:, :nfilt]

        PJ0 = rearrange_PJ(PJ0, ioff.size, fhtfilt.base.size)
        PJ1 = rearrange_PJ(PJ1, ioff.size, fhtfilt.base.size)
        PJ0b = rearrange_PJ(PJ0b, ioff.size, fhtfilt.base.size)

    # 3. ANGLE DEPENDENT FACTORS
    factAng = kernel.angle_factor(angle, ab, msrc, mrec)
    one_angle = (factAng - factAng[0] == 0).all()

    # 4. CARRY OUT THE FHT
    if use_spline and one_angle:  # SPLINE, ALL ANGLES ARE EQUAL
        # If all offsets are in one line from the source, hence have the same
        # angle, we can combine PJ0 and PJ0b and save one FHT, and combine both
        # into one function to interpolate.

        # 1. FHT
        EM_int = factAng[0]*np.dot(PJ1, fhtfilt.j1)
        if ab in [11, 12, 21, 22, 14, 24, 15, 25]:  # Because of J2
            # J2(kr) = 2/(kr)*J1(kr) - J0(kr)
            EM_int /= ioff
        EM_int += np.dot(PJ0 + factAng[0]*PJ0b, fhtfilt.j0)

        # 2. Interpolation
        real_EM = iuSpline(np.log10(ioff[::-1]), EM_int.real[::-1])
        imag_EM = iuSpline(np.log10(ioff[::-1]), EM_int.imag[::-1])
        fEM = real_EM(np.log10(off)) + 1j*imag_EM(np.log10(off))

    elif use_spline:  # SPLINE, VARYING ANGLES
        # If not all offsets are in one line from the source, hence do not have
        # the same angle, the whole process has to be done separately for
        # angle-dependent and angle-independent parts. This means one FHT more,
        # and two (instead of one) functions to interpolate.

        # 1. FHT
        # Separated in an angle-dependent and a non-dependent part
        EM_noang = np.dot(PJ0, fhtfilt.j0)
        EM_angle = np.dot(PJ1, fhtfilt.j1)
        if ab in [11, 12, 21, 22, 14, 24, 15, 25]:  # Because of J2
            # J2(kr) = 2/(kr)*J1(kr) - J0(kr)
            EM_angle /= ioff
        EM_angle += np.dot(PJ0b, fhtfilt.j0)

        # 2. Interpolation
        # Separately on EM_noang and EM_angle
        real_noang = iuSpline(np.log10(ioff[::-1]), EM_noang.real[::-1])
        imag_noang = iuSpline(np.log10(ioff[::-1]), EM_noang.imag[::-1])
        real_angle = iuSpline(np.log10(ioff[::-1]), EM_angle.real[::-1])
        imag_angle = iuSpline(np.log10(ioff[::-1]), EM_angle.imag[::-1])

        # Get fEM-field at required offsets
        EM_noang = real_noang(np.log10(off)) + 1j*imag_noang(np.log10(off))
        EM_angle = real_angle(np.log10(off)) + 1j*imag_angle(np.log10(off))

        # Angle dependency
        fEM = (factAng*EM_angle + EM_noang)

    else:  # NO SPLINE
        # Without spline, we can combine PJ0 and PJ0b to save one FHT, even if
        # all offsets have a different angle.
        fEM = factAng*np.dot(PJ1, fhtfilt.j1)
        if ab in [11, 12, 21, 22, 14, 24, 15, 25]:  # Because of J2
            # J2(kr) = 2/(kr)*J1(kr) - J0(kr)
            fEM /= off
        fEM += np.dot(PJ0 + factAng[:, np.newaxis]*PJ0b, fhtfilt.j0)

    # Return the electromagnetic field, normalize by offset
    # Second argument (1) is the kernel count
    # (Last argument is only for QWE)
    return fEM/off, 1, True


def hqwe(zsrc, zrec, lsrc, lrec, off, angle, depth, ab, etaH, etaV, zetaH,
         zetaV, xdirect, qweargs, use_spline, use_ne_eval, msrc, mrec):
    """Hankel Transform using Quadrature-With-Extrapolation.

    *Quadrature-With-Extrapolation* was introduced to geophysics by
    [Key_2012]_. It is one of many so-called *ISE* methods to solve Hankel
    Transforms, where *ISE* stands for Integration, Summation, and
    Extrapolation.

    Following [Key_2012]_, but without going into the mathematical details
    here, the QWE method rewrites the Hankel transform of the form

    .. math:: F(r)   = \int^\infty_0 f(\lambda)J_v(\lambda r)\
            \mathrm{d}\lambda

    as a quadrature sum which form is similar to the FHT (equation 15),

    .. math::   F_i   \\approx \sum^m_{j=1} f(x_j/r)w_j g(x_j) =
                \sum^m_{j=1} f(x_j/r)\hat{g}(x_j) \ ,

    but with various bells and whistles applied (using the so-called Shanks
    transformation in the form of a routine called :math:`\epsilon`-algorithm
    ([Shanks_1955]_, [Wynn_1956]_; implemented with algorithms from
    [Trefethen_2000]_ and [Weniger_1989]_).

    This function is based on `get_CSEM1D_FD_QWE.m`, `qwe.m`, and
    `getBesselWeights.m` from the source code distributed with [Key_2012]_.

    In the spline-version, `hqwe` checks how steep the decay of the
    wavenumber-domain result is, and calls QUAD for the very steep interval,
    for which QWE is not suited.

    The function is called from one of the modelling routines in :mod:`model`.
    Consult these modelling routines for a description of the input and output
    parameters.

    Returns
    -------
    fEM : array
        Returns frequency-domain EM response.

    kcount : int
        Kernel count.

    conv : bool
        If true, QWE/QUAD converged. If not, <htarg> might have to be adjusted.

    """
    # Input params have an additional dimension for frequency, reduce here
    etaH = etaH[0, :]
    etaV = etaV[0, :]
    zetaH = zetaH[0, :]
    zetaV = zetaV[0, :]

    # Get rtol, atol, nquad, maxint, and pts_per_dec
    rtol, atol, nquad, maxint, pts_per_dec = qweargs[:5]

    # 1. PRE-COMPUTE THE BESSEL FUNCTIONS
    # at fixed quadrature points for each interval and multiply by the
    # corresponding Gauss quadrature weights

    # Get Gauss quadrature weights
    g_x, g_w = special.p_roots(nquad)

    # Compute n zeros of the Bessel function of the first kind of order 1 using
    # the Newton-Raphson method, which is fast enough for our purposes.  Could
    # be done with a loop for (but it is slower):
    # b_zero[i] = optimize.newton(special.j1, b_zero[i])

    # Initial guess using asymptotic zeros
    b_zero = np.pi*np.arange(1.25, maxint+1)

    # Newton-Raphson iterations
    for i in range(10):   # 10 is more than enough, usually stops in 5

        # Evaluate
        b_x0 = special.j1(b_zero)     # j0 and j1 have faster versions
        b_x1 = special.jv(2, b_zero)  # j2 does not have a faster version

        # The step length
        b_h = -b_x0/(b_x0/b_zero - b_x1)

        # Take the step
        b_zero += b_h

        # Check for convergence
        if all(np.abs(b_h) < 8*np.finfo(float).eps*b_zero):
            break

    # 2. COMPUTE THE QUADRATURE INTERVALS AND BESSEL FUNCTION WEIGHTS

    # Lower limit of integrand, a small but non-zero value
    xint = np.concatenate((np.array([1e-20]), b_zero))

    # Assemble the output arrays
    dx = np.repeat(np.diff(xint)/2, nquad)
    Bx = dx*(np.tile(g_x, maxint) + 1) + np.repeat(xint[:-1], nquad)
    BJ0 = special.j0(Bx)*np.tile(g_w, maxint)
    BJ1 = special.j1(Bx)*np.tile(g_w, maxint)

    # 3. START QWE

    # Intervals and lambdas for all offset
    intervals = xint/off[:, None]
    lambd = Bx/off[:, None]

    # Angle dependent factors
    factAng = kernel.angle_factor(angle, ab, msrc, mrec)

    # Call and return QWE, depending if spline or not
    if use_spline:  # If spline, we calculate all kernels here
        # New lambda, from min to max required lambda with pts_per_dec
        start = np.log10(lambd.min())
        stop = np.log10(lambd.max())
        ilambd = np.logspace(start, stop, (stop-start)*pts_per_dec + 1)

        # Call the kernel
        PJ0, PJ1, PJ0b = kernel.wavenumber(zsrc, zrec, lsrc, lrec, depth,
                                           etaH[None, :], etaV[None, :],
                                           zetaH[None, :], zetaV[None, :],
                                           np.atleast_2d(ilambd), ab, xdirect,
                                           msrc, mrec, use_ne_eval)

        # Interpolation : Has to be done separately on each PJ,
        # in order to work with multiple offsets which have different angles.
        sPJ0r = iuSpline(np.log10(ilambd), PJ0.real)
        sPJ0i = iuSpline(np.log10(ilambd), PJ0.imag)
        sPJ1r = iuSpline(np.log10(ilambd), PJ1.real)
        sPJ1i = iuSpline(np.log10(ilambd), PJ1.imag)
        sPJ0br = iuSpline(np.log10(ilambd), PJ0b.real)
        sPJ0bi = iuSpline(np.log10(ilambd), PJ0b.imag)

        # Get quadargs: diff_quad, a, b, limit
        diff_quad, a, b, limit = qweargs[5:]

        # Set quadargs if not given:
        if not limit:
            limit = maxint
        if not a:
            a = intervals[:, 0]
        else:
            a = a*np.ones(off.shape)
        if not b:
            b = intervals[:, -1]
        else:
            b = b*np.ones(off.shape)

        # Check if we use QWE or SciPy's QUAD
        # If there are any steep decays within an interval we have to use QUAD,
        # as QWE is not designed for these intervals.
        check0 = np.log10(intervals[:, :-1])
        check1 = np.log10(intervals[:, 1:])
        doqwe = np.all((np.abs(sPJ0r(check0) + 1j*sPJ0i(check0) +
                        sPJ1r(check0) + 1j*sPJ1i(check0) +
                        sPJ0br(check0) + 1j*sPJ0bi(check0)) /
                        np.abs(sPJ0r(check1) + 1j*sPJ0i(check1) +
                        sPJ1r(check1) + 1j*sPJ1i(check1) +
                        sPJ0br(check1) + 1j*sPJ0bi(check1)) < diff_quad), 1)

        # Pre-allocate output array
        fEM = np.zeros(off.size, dtype=complex)
        conv = True

        # Carry out SciPy's Quad if required
        if np.any(~doqwe):

            # Loop over offsets that require Quad
            for i in np.where(~doqwe)[0]:

                # Input-dictionary for quad
                iinp = {'a': a[i], 'b': b[i], 'epsabs': atol, 'epsrel': rtol,
                        'limit': limit}

                fEM[i], tc = quad(sPJ0r, sPJ0i, sPJ1r, sPJ1i, sPJ0br, sPJ0bi,
                                  ab, off[i], factAng[i], iinp)

                # Update conv
                conv *= tc

            # Return kcount=1 in case no QWE is calculated
            kcount = 1

        if np.any(doqwe):
            # Get EM-field at required offsets
            sPJ0 = sPJ0r(np.log10(lambd)) + 1j*sPJ0i(np.log10(lambd))
            sPJ1 = sPJ1r(np.log10(lambd)) + 1j*sPJ1i(np.log10(lambd))
            sPJ0b = sPJ0br(np.log10(lambd)) + 1j*sPJ0bi(np.log10(lambd))

            # Carry out and return the Hankel transform for this interval
            sEM = np.sum(np.reshape(sPJ1*BJ1, (off.size, nquad, -1),
                         order='F'), 1)
            if ab in [11, 12, 21, 22, 14, 24, 15, 25]:  # Because of J2
                # J2(kr) = 2/(kr)*J1(kr) - J0(kr)
                sEM /= np.atleast_1d(off[:, np.newaxis])
            sEM += np.sum(np.reshape(sPJ0b*BJ0, (off.size, nquad, -1),
                                     order='F'), 1)
            sEM *= factAng[:, np.newaxis]
            sEM += np.sum(np.reshape(sPJ0*BJ0, (off.size, nquad, -1),
                                     order='F'), 1)

            getkernel = sEM[doqwe, :]

            # Get QWE
            fEM[doqwe], kcount, tc = qwe(rtol, atol, maxint, getkernel,
                                         intervals[doqwe, :], None, None, None)
            conv *= tc

    else:  # If not spline, we define the wavenumber-kernel here
        def getkernel(i, inplambd, inpoff, inpfang):
            """Return wavenumber-domain-kernel as a fct of interval i."""

            # Indices and factor for this interval
            iB = i*nquad + np.arange(nquad)

            # PJ0 and PJ1 for this interval
            PJ0, PJ1, PJ0b = kernel.wavenumber(zsrc, zrec, lsrc, lrec, depth,
                                               etaH[None, :], etaV[None, :],
                                               zetaH[None, :], zetaV[None, :],
                                               np.atleast_2d(inplambd)[:, iB],
                                               ab, xdirect, msrc, mrec,
                                               use_ne_eval)

            # Carry out and return the Hankel transform for this interval
            gEM = inpfang*np.dot(PJ1[0, :], BJ1[iB])
            if ab in [11, 12, 21, 22, 14, 24, 15, 25]:  # Because of J2
                # J2(kr) = 2/(kr)*J1(kr) - J0(kr)
                gEM /= np.atleast_1d(inpoff)
            gEM += inpfang*np.dot(PJ0b[0, :], BJ0[iB])
            gEM += np.dot(PJ0[0, :], BJ0[iB])

            return gEM

        # Get QWE
        fEM, kcount, conv = qwe(rtol, atol, maxint, getkernel, intervals,
                                lambd, off, factAng)

    return fEM, kcount, conv


def hquad(zsrc, zrec, lsrc, lrec, off, angle, depth, ab, etaH, etaV, zetaH,
          zetaV, xdirect, quadargs, use_spline, use_ne_eval, msrc, mrec):
    """Hankel Transform using the QUADPACK library.

    This routine uses the `scipy.integrate.quad` module, which in turn makes
    use of the Fortran library `QUADPACK` (`qagse`).

    It is massively (orders of magnitudes) slower than either `fht` or `hqwe`,
    and is mainly here for completeness and comparison purposes. It always uses
    interpolation in the wavenumber domain, hence it generally will not be as
    precise as the other methods. However, it might work in some areas where
    the others fail.

    The function is called from one of the modelling routines in :mod:`model`.
    Consult these modelling routines for a description of the input and output
    parameters.

    Returns
    -------
    fEM : array
        Returns frequency-domain EM response.

    kcount : int
        Kernel count. For HQUAD, this is 1.

    conv : bool
        If true, QUAD converged. If not, <htarg> might have to be adjusted.

    """

    # Get quadargs
    rtol, atol, limit, a, b, pts_per_dec = quadargs

    # Get required lambdas
    la = np.log10(a)
    lb = np.log10(b)
    ilambd = np.logspace(la, lb, (lb-la)*pts_per_dec + 1)

    # Call the kernel
    PJ0, PJ1, PJ0b = kernel.wavenumber(zsrc, zrec, lsrc, lrec, depth, etaH,
                                       etaV, zetaH, zetaV,
                                       np.atleast_2d(ilambd), ab, xdirect,
                                       msrc, mrec, use_ne_eval)

    # Interpolation in wavenumber domain: Has to be done separately on each PJ,
    # in order to work with multiple offsets which have different angles.
    sPJ0r = iuSpline(np.log10(ilambd), PJ0.real)
    sPJ0i = iuSpline(np.log10(ilambd), PJ0.imag)

    sPJ1r = iuSpline(np.log10(ilambd), PJ1.real)
    sPJ1i = iuSpline(np.log10(ilambd), PJ1.imag)

    sPJ0br = iuSpline(np.log10(ilambd), PJ0b.real)
    sPJ0bi = iuSpline(np.log10(ilambd), PJ0b.imag)

    # Get the angle factor
    factAng = kernel.angle_factor(angle, ab, msrc, mrec)

    # Pre-allocate output array
    fEM = np.zeros(off.size, dtype=complex)
    conv = True

    # Input-dictionary for quad
    iinp = {'a': a, 'b': b, 'epsabs': atol, 'epsrel': rtol, 'limit': limit}

    # Loop over offsets
    for i in range(off.size):
        fEM[i], tc = quad(sPJ0r, sPJ0i, sPJ1r, sPJ1i, sPJ0br, sPJ0bi, ab,
                          off[i], factAng[i], iinp)
        conv *= tc

    # Return the electromagnetic field
    # Second argument (1) is the kernel count, last argument is only for QWE.
    return fEM, 1, conv


# 2. Fourier transforms (frequency -> time)

def ffht(fEM, time, freq, ftarg):
    """Fourier Transform using a Cosine- or a Sine-filter.

    It follows the Filter methodology [Anderson_1975]_, see `fht` for more
    information.

    The function is called from one of the modelling routines in :mod:`model`.
    Consult these modelling routines for a description of the input and output
    parameters.

    This function is based on `get_CSEM1D_TD_FHT.m` from the source code
    distributed with [Key_2012]_.

    Returns
    -------
    tEM : array
        Returns time-domain EM response of `fEM` for given `time`.

    conv : bool
        Only relevant for QWE/QUAD.

    """
    # Get ftarg values
    fftfilt, pts_per_dec, ftkind = ftarg

    # Settings depending if cos/sin plus scaling
    if ftkind == 'sin':
        fEM = -fEM.imag
    else:
        fEM = fEM.real

    if pts_per_dec:  # Use pts_per_dec frequencies per decade
        # 1. Interpolate in frequency domain
        sfEM = iuSpline(np.log10(2*np.pi*freq), fEM)
        ifEM = sfEM(np.log10(fftfilt.base/time[:, None]))

        # 2. Filter
        tEM = np.dot(ifEM, getattr(fftfilt, ftkind))

    else:  # Standard FHT procedure
        # Get new times in frequency domain
        _, itime = get_spline_values(fftfilt, time)

        # Re-arranged fEM with shape (ntime, nfreq).  Each row starts one
        # 'freq' higher.
        fEM = np.concatenate((np.tile(fEM, itime.size).squeeze(),
                             np.zeros(itime.size)))
        fEM = fEM.reshape(itime.size, -1)[:, :fftfilt.base.size]

        # 1. Filter
        stEM = np.dot(fEM, getattr(fftfilt, ftkind))

        # 2. Interpolate in time domain
        itEM = iuSpline(np.log10((itime)[::-1]), stEM[::-1])
        tEM = itEM(np.log10(time))

    # Return the electromagnetic time domain field
    # (Second argument is only for QWE)
    return tEM/time, True


def fqwe(fEM, time, freq, qweargs):
    """Fourier Transform using Quadrature-With-Extrapolation.

    It follows the QWE methodology [Key_2012]_ for the Hankel transform, see
    `hqwe` for more information.

    The function is called from one of the modelling routines in :mod:`model`.
    Consult these modelling routines for a description of the input and output
    parameters.

    This function is based on `get_CSEM1D_TD_QWE.m` from the source code
    distributed with [Key_2012]_.

    `fqwe` checks how steep the decay of the frequency-domain result is, and
    calls QUAD for the very steep interval, for which QWE is not suited.

    Returns
    -------
    tEM : array
        Returns time-domain EM response of `fEM` for given `time`.

    conv : bool
        If true, QWE/QUAD converged. If not, <ftarg> might have to be adjusted.

    """
    # Get rtol, atol, nquad, maxint, diff_quad, a, b, and limit
    rtol, atol, nquad, maxint, _, diff_quad, a, b, limit, sincos = qweargs

    # Calculate quadrature intervals for all offset
    xint = np.concatenate((np.array([1e-20]), np.arange(1, maxint+1)*np.pi))
    if sincos == np.cos:  # Adjust zero-crossings if cosine-transform
        xint[1:] -= np.pi/2
    intervals = xint/time[:, None]

    # Get Gauss Quadrature Weights
    g_x, g_w = special.p_roots(nquad)

    # Pre-compute the Bessel functions at fixed quadrature points, multiplied
    # by the corresponding Gauss quadrature weight.
    dx = np.repeat(np.diff(xint)/2, nquad)
    Bx = dx*(np.tile(g_x, maxint) + 1) + np.repeat(xint[:-1], nquad)
    SS = sincos(Bx)*np.tile(g_w, maxint)

    # Interpolate in frequency domain
    tEM_rint = iuSpline(np.log10(2*np.pi*freq), fEM.real)
    tEM_iint = iuSpline(np.log10(2*np.pi*freq), -fEM.imag)

    # Check if we use QWE or SciPy's QUAD
    # If there are any steep decays within an interval we have to use QUAD, as
    # QWE is not designed for these intervals.
    check0 = np.log10(intervals[:, :-1])
    check1 = np.log10(intervals[:, 1:])
    doqwe = np.all((np.abs(tEM_rint(check0) + 1j*tEM_iint(check0)) /
                   np.abs(tEM_rint(check1) + 1j*tEM_iint(check1)) < diff_quad),
                   1)

    # Choose imaginary part if sine-transform, else real part
    if sincos == np.sin:
        tEM_int = tEM_iint
    else:
        tEM_int = tEM_rint

    # Set quadargs if not given:
    if not limit:
        limit = maxint
    if not a:
        a = intervals[:, 0]
    else:
        a = a*np.ones(time.shape)
    if not b:
        b = intervals[:, -1]
    else:
        b = b*np.ones(time.shape)

    # Pre-allocate output array
    tEM = np.zeros(time.size)
    conv = True

    # Carry out SciPy's Quad if required
    if np.any(~doqwe):
        def sEMquad(w, t):
            """Return scaled, interpolated value of tEM_int for `w`."""
            return tEM_int(np.log10(w))*sincos(w*t)

        # Loop over times that require QUAD
        for i in np.where(~doqwe)[0]:
            out = integrate.quad(sEMquad, a[i], b[i], (time[i],), 1, atol,
                                 rtol, limit)
            tEM[i] = out[0]

            # If there is a fourth output from QUAD, it means it did not conv.
            if len(out) > 3:
                conv *= False

    # Carry out QWE for 'well-behaved' intervals
    if np.any(doqwe):
        sEM = tEM_int(np.log10(Bx/time[doqwe, None]))*SS
        tEM[doqwe], _, tc = qwe(rtol, atol, maxint, sEM, intervals[doqwe, :])
        conv *= tc

    return tEM, conv


def fftlog(fEM, time, freq, ftarg):
    """Fourier Transform using FFTLog.

    FFTLog is the logarithmic analogue to the Fast Fourier Transform FFT.
    FFTLog was presented in Appendix B of [Hamilton_2000]_ and published at
    <http://casa.colorado.edu/~ajsh/FFTLog>.

    This function uses a simplified version of `pyfftlog`, which is a
    python-version of `FFTLog`. For more details regarding `pyfftlog` see
    <https://github.com/prisae/pyfftlog>.

    Not the full flexibility of `FFTLog` is available here: Only the
    logarithmic FFT (`fftl` in `FFTLog`), not the Hankel transform (`fht` in
    `FFTLog`). Furthermore, the following parameters are fixed:

       - `kr` = 1 (initial value)
       - `kropt` = 1 (silently adjusts `kr`)
       - `dir` = 1 (forward)

    Furthermore, `q` is restricted to -1 <= q <= 1.

    The function is called from one of the modelling routines in :mod:`model`.
    Consult these modelling routines for a description of the input and output
    parameters.

    Returns
    -------
    tEM : array
        Returns time-domain EM response of `fEM` for given `time`.

    conv : bool
        Only relevant for QWE/QUAD.

    """
    # Get tcalc, dlnr, kr, rk, q; a and n
    _, _, q, mu, tcalc, dlnr, kr, rk = ftarg
    if mu > 0:  # Sine
        a = -fEM.imag
    else:       # Cosine
        a = fEM.real
    n = a.size

    # 1. Amplitude and Argument of kr^(-2 i y) U_mu(q + 2 i y)
    ln2kr = np.log(2.0/kr)
    d = np.pi/(n*dlnr)
    m = np.arange(1, (n+1)/2)
    y = m*d  # y = m*pi/(n*dlnr)

    if q == 0:  # unbiased case (q = 0)
        zp = special.loggamma((mu + 1)/2.0 + 1j*y)
        arg = 2.0*(ln2kr*y + zp.imag)

    else:       # biased case (q != 0)
        xp = (mu + 1.0 + q)/2.0
        xm = (mu + 1.0 - q)/2.0

        zp = special.loggamma(xp + 0j)
        zm = special.loggamma(xm + 0j)

        # Amplitude and Argument of U_mu(q)
        amp = np.exp(np.log(2.0)*q + zp.real - zm.real)
        # note +Im(zm) to get conjugate value below real axis
        arg = zp.imag + zm.imag

        # first element: cos(arg) = ±1, sin(arg) = 0
        argcos1 = amp*np.cos(arg)

        # remaining elements
        zp = special.loggamma(xp + 1j*y)
        zm = special.loggamma(xm + 1j*y)

        argamp = np.exp(np.log(2.0)*q + zp.real - zm.real)
        arg = 2*ln2kr*y + zp.imag + zm.imag

    argcos = np.cos(arg)
    argsin = np.sin(arg)

    # 2. Centre point of array
    jc = np.array((n + 1)/2.0)
    j = np.arange(n)+1

    # 3. a(r) = A(r) (r/rc)^[-dir*(q-.5)]
    a *= np.exp(-(q - 0.5)*(j - jc)*dlnr)

    # 4. transform a(r) -> ã(k)

    # 4.a normal FFT
    a = fftpack.rfft(a)

    # 4.b
    m = np.arange(1, n/2, dtype=int)  # index variable
    if q == 0:  # unbiased (q = 0) transform
        # multiply by (kr)^[- i 2 m pi/(n dlnr)] U_mu[i 2 m pi/(n dlnr)]
        ar = a[2*m-1]
        ai = a[2*m]
        a[2*m-1] = ar*argcos[:-1] - ai*argsin[:-1]
        a[2*m] = ar*argsin[:-1] + ai*argcos[:-1]
        # problematical last element, for even n
        if np.mod(n, 2) == 0:
            ar = argcos[-1]
            a[-1] *= ar

    else:  # biased (q != 0) transform
        # multiply by (kr)^[- i 2 m pi/(n dlnr)] U_mu[q + i 2 m pi/(n dlnr)]
        # phase
        ar = a[2*m-1]
        ai = a[2*m]
        a[2*m-1] = ar*argcos[:-1] - ai*argsin[:-1]
        a[2*m] = ar*argsin[:-1] + ai*argcos[:-1]

        a[0] *= argcos1
        a[2*m-1] *= argamp[:-1]
        a[2*m] *= argamp[:-1]

        # problematical last element, for even n
        if np.mod(n, 2) == 0:
            m = int(n/2)-3
            ar = argcos[m-1]*argamp[m-1]
            a[-1] *= ar

    # 4.c normal FFT back
    a = fftpack.irfft(a)

    # Ã(k) = ã(k) k^[-dir*(q+.5)] rc^[-dir*(q-.5)]
    #      = ã(k) (k/kc)^[-dir*(q+.5)] (kc rc)^(-dir*q) (rc/kc)^(dir*.5)
    a = a[::-1]*np.exp(-((q + 0.5)*(j - jc)*dlnr + q*np.log(kr) -
                       np.log(rk)/2.0))

    # Interpolate for the desired times
    ttEM = iuSpline(np.log10(tcalc), a)
    tEM = ttEM(np.log10(time))

    # (Second argument is only for QWE)
    return tEM, True


def fft(fEM, time, freq, ftarg):
    """Fourier Transform using the Fast Fourier Transform.

    The function is called from one of the modelling routines in :mod:`model`.
    Consult these modelling routines for a description of the input and output
    parameters.

    Returns
    -------
    tEM : array
        Returns time-domain EM response of `fEM` for given `time`.

    conv : bool
        Only relevant for QWE/QUAD.

    """
    # Get ftarg values
    dfreq, nfreq, ntot, pts_per_dec = ftarg

    # If pts_per_dec, we have first to interpolate fEM to required freqs
    if pts_per_dec:
        sfEMr = iuSpline(np.log10(freq), fEM.real)
        sfEMi = iuSpline(np.log10(freq), fEM.imag)
        freq = np.arange(1, nfreq+1)*dfreq
        fEM = sfEMr(np.log10(freq)) + 1j*sfEMi(np.log10(freq))

    # Pad the frequency result
    fEM = np.pad(fEM, (0, ntot-nfreq), 'linear_ramp')

    # Carry out FFT
    ifftEM = fftpack.ifft(np.r_[fEM[1:], 0, fEM[::-1].conj()]).real
    stEM = 2*ntot*fftpack.fftshift(ifftEM*dfreq, 0)

    # Interpolate in time domain
    dt = 1/(2*ntot*dfreq)
    ifEM = iuSpline(np.linspace(-ntot, ntot-1, 2*ntot)*dt, stEM)
    tEM = ifEM(time)/2*np.pi  # (Multiplication of 2/pi in model.tem)

    # Return the electromagnetic time domain field
    # (Second argument is only for QWE)
    return tEM, True


# 3. Utilities

def qwe(rtol, atol, maxint, inp, intervals, lambd=None, off=None,
        factAng=None):
    """Quadrature-With-Extrapolation.

    This is the kernel of the QWE method, used for the Hankel (`hqwe`) and the
    Fourier (`fqwe`) Transforms. See `hqwe` for an extensive description.

    This function is based on `qwe.m` from the source code distributed with
    [Key_2012]_.

    """
    def getweights(i, inpint):
        """Return weights for this interval."""
        return (np.atleast_2d(inpint)[:,  i+1] - np.atleast_2d(inpint)[:, i])/2

    # 1. Calculate the first interval for all offsets
    if hasattr(inp, '__call__'):  # Hankel and not spline
        EM0 = inp(0, lambd, off, factAng)
    else:                         # Fourier or Hankel with spline
        EM0 = inp[:, 0]
    EM0 *= getweights(0, intervals)

    # 2. Pre-allocate arrays and initialize
    EM = np.zeros(EM0.size, dtype=EM0.dtype)                # EM array
    om = np.ones(EM0.size, dtype=bool)                      # Convergence array
    S = np.zeros((EM0.size, maxint), dtype=EM0.dtype)  # Working arr. 4 recurs.
    relErr = np.zeros((EM0.size, maxint))                   # Relative error
    extrap = np.zeros((EM0.size, maxint), dtype=EM0.dtype)  # extrap. result
    kcount = 1  # Initialize kernel count (only important for Hankel)

    # 3. The extrapolation transformation loop
    for i in range(1, maxint):
        # 3.a Calculate the field for this interval
        if hasattr(inp, '__call__'):  # Hankel and not spline
            EMi = inp(i, lambd[om, :], off[om], factAng[om])
            kcount += 1  # Update count
        else:                         # Fourier or Hankel with spline
            EMi = inp[om, i]
        EMi *= getweights(i, intervals[om, :])

        # 3.b Compute Shanks transformation
        # Using the epsilon algorithm: structured after [Weniger_1989]_, p26.
        S[:, i][om] = S[:, i-1][om] + EMi  # working array for transformation

        # Recursive loop
        aux2 = np.zeros(om.sum(), dtype=EM0.dtype)
        for k in range(i, 0, -1):
            aux1, aux2 = aux2, S[om, k-1]
            ddff = S[om, k] - aux2
            S[om, k-1] = np.where(np.abs(ddff) < np.finfo(np.double).tiny,
                                  np.finfo(np.double).max, aux1 + 1/ddff)

        # The extrapolated result plus the first interval term
        extrap[om, i-1] = S[om, np.mod(i, 2)] + EM0[om]

        # 3.c Analyze for convergence
        if i > 1:
            # Calculate relative and absolute error
            rErr = (extrap[om, i-1] - extrap[om, i-2])/extrap[om, i-1]
            relErr[om, i-1] = np.abs(rErr)
            abserr = atol/np.abs(extrap[om, i-1])

            # Update booleans
            om[om] *= relErr[om, i-1] >= rtol + abserr

            # Store in EM
            EM[om] = extrap[om, i-1]

        if (~om).all():
            break

    # 4. Cleaning up

    # Warning if maxint is potentially too small
    conv = i+1 != maxint

    # Catch the ones that did not converge
    EM[om] = extrap[om, i-1]

    # Set np.finfo(np.double).max to 0
    EM.real[EM.real == np.finfo(np.double).max] = 0

    return EM, kcount, conv


def quad(sPJ0r, sPJ0i, sPJ1r, sPJ1i, sPJ0br, sPJ0bi, ab, off, factAng, iinp):
    """Quadrature for Hankel transform.

    This is the kernel of the QUAD method, used for the Hankel transforms
    `hquad` and `hqwe` (where the integral is not suited for QWE).

    """

    # Define the quadrature kernels
    def quad0(klambd, sPJ, sPJb, koff, kang):
        """Quadrature for J0."""
        tP0 = sPJ(np.log10(klambd)) + kang*sPJb(np.log10(klambd))
        return tP0*special.j0(koff*klambd)

    def quad1(klambd, sPJ, ab, koff, kang):
        """Quadrature for J1."""
        tP1 = kang*sPJ(np.log10(klambd))
        if ab in [11, 12, 21, 22, 14, 24, 15, 25]:  # Because of J2
            # J2(kr) = 2/(kr)*J1(kr) - J0(kr)
            tP1 /= koff
        return tP1*special.j1(koff*klambd)

    # Carry out quadrature of J0
    iargs = (sPJ0r, sPJ0br, off, factAng)
    fr0 = integrate.quad(quad0, args=iargs, full_output=1, **iinp)
    iargs = (sPJ0i, sPJ0bi, off, factAng)
    fi0 = integrate.quad(quad0, args=iargs, full_output=1, **iinp)

    # Carry out quadrature of J1
    iargs = (sPJ1r, ab, off, factAng)
    fr1 = integrate.quad(quad1, args=iargs, full_output=1, **iinp)
    iargs = (sPJ1i, ab, off, factAng)
    fi1 = integrate.quad(quad1, args=iargs, full_output=1, **iinp)

    # If there is a fourth output from QUAD, it means it did not converge
    if np.any(np.array([len(fr0), len(fi0), len(fr1), len(fi1)]) > 3):
        conv = False
    else:
        conv = True

    # Collect the results
    return fr0[0] + fr1[0] + 1j*(fi0[0] + fi1[0]), conv


def get_spline_values(filt, inp, nr_per_dec=None):
    """Return required calculation points."""

    # If number per decade (nr_per_dec) is not provided, filter.factor is used
    if not nr_per_dec:
        nr_per_dec = 1/np.log(filt.factor)

    # Get min and max required out-values (depends on filter and inp-value)
    outmax = filt.base[-1]/inp.min()
    outmin = filt.base[0]/inp.max()

    # Number of out-values
    nout = int(np.ceil(np.log(outmax/outmin)*nr_per_dec) + 1)
    # The cubic InterpolatedUnivariateSpline needs at least 4 points
    if nout-filt.base.size < 3:
        nout = filt.base.size+3

    # Calculate output values
    out = np.exp(np.arange(np.log(outmin), np.log(outmin) + nout/nr_per_dec,
                           1/nr_per_dec))

    # Only necessary if standard spline is used. We need to calculate the new
    # input values, as spline is carried out in the input domain. Else spline
    # is carried out in output domain and the new input values are not used.
    new_inp = inp.max()*np.exp(-np.arange(nout - filt.base.size + 1) /
                               nr_per_dec)

    # Return output values
    return np.atleast_2d(out), new_inp


def fhti(rmin, rmax, n, q, mu):
    """Return parameters required for FFTLog."""

    # Central point log10(r_c) of periodic interval
    logrc = (rmin + rmax)/2

    # Central index (1/2 integral if n is even)
    nc = (n + 1)/2.

    # Log spacing of points
    dlogr = (rmax - rmin)/n
    dlnr = dlogr*np.log(10.)

    # Get low-ringing kr
    y = 1j*np.pi/(2.0*dlnr)
    zp = special.loggamma((mu + 1.0 + q)/2.0 + y)
    zm = special.loggamma((mu + 1.0 - q)/2.0 + y)
    arg = np.log(2.0)/dlnr + (zp.imag + zm.imag)/np.pi
    kr = np.exp((arg - np.round(arg))*dlnr)

    # Calculate required input x-values (freq); angular freq -> freq
    freq = 10**(logrc + (np.arange(1, n+1) - nc)*dlogr)/(2*np.pi)

    # Calculate tcalc with adjusted kr
    logkc = np.log10(kr) - logrc
    tcalc = 10**(logkc + (np.arange(1, n+1) - nc)*dlogr)

    # rk = r_c/k_r; adjust for Fourier transform scaling
    rk = 10**(logrc - logkc)*np.pi/2

    return freq, tcalc, dlnr, kr, rk
