# -*- coding: utf-8 -*-
"""Pulsed frequency sweep on the resonator with and without a π/2 control pulse."""
import h5py
import numpy as np

from presto.hardware import AdcFSample, AdcMode, DacFSample, DacMode
from presto import pulsed
from presto.utils import sin2, untwist_downconversion

from _base import Base

DAC_CURRENT = 32_000  # uA
CONVERTER_CONFIGURATION = {
    "adc_mode": AdcMode.Mixed,
    "adc_fsample": AdcFSample.G4,
    "dac_mode": [DacMode.Mixed42, DacMode.Mixed02, DacMode.Mixed02, DacMode.Mixed02],
    "dac_fsample": [DacFSample.G10, DacFSample.G6, DacFSample.G6, DacFSample.G6],
}
IDX_LOW = 1_500
IDX_HIGH = 2_000


class ExcitedSweep(Base):
    def __init__(
        self,
        readout_freq_center: float,
        readout_freq_span: float,
        readout_freq_nr: int,
        control_freq: float,
        readout_amp: float,
        control_amp: float,
        readout_duration: float,
        control_duration: float,
        sample_duration: float,
        readout_port: int,
        control_port: int,
        sample_port: int,
        wait_delay: float,
        readout_sample_delay: float,
        num_averages: int,
        drag: float = 0.0,
    ) -> None:
        self.readout_freq_center = readout_freq_center
        self.readout_freq_span = readout_freq_span
        self.readout_freq_nr = readout_freq_nr
        self.control_freq = control_freq
        self.readout_amp = readout_amp
        self.control_amp = control_amp
        self.readout_duration = readout_duration
        self.control_duration = control_duration
        self.sample_duration = sample_duration
        self.readout_port = readout_port
        self.control_port = control_port
        self.sample_port = sample_port
        self.wait_delay = wait_delay
        self.readout_sample_delay = readout_sample_delay
        self.num_averages = num_averages
        self.drag = drag

        self.readout_freq_arr = None  # replaced by run
        self.readout_if_arr = None  # replaced by run
        self.readout_nco = None  # replaced by run
        self.t_arr = None  # replaced by run
        self.store_arr = None  # replaced by run

    def run(
        self,
        presto_address: str,
        presto_port: int = None,
        ext_ref_clk: bool = False,
    ) -> str:
        # Instantiate interface class
        with pulsed.Pulsed(
            address=presto_address,
            port=presto_port,
            ext_ref_clk=ext_ref_clk,
            **CONVERTER_CONFIGURATION,
        ) as pls:
            assert pls.hardware is not None

            # figure out frequencies
            assert self.readout_freq_center > (self.readout_freq_span / 2)
            assert self.readout_freq_span < pls.get_fs("dac") / 2  # fits in HSB
            readout_if_center = pls.get_fs("dac") / 4  # middle of HSB
            readout_if_start = readout_if_center - self.readout_freq_span / 2
            readout_if_stop = readout_if_center + self.readout_freq_span / 2
            self.readout_if_arr = np.linspace(
                readout_if_start, readout_if_stop, self.readout_freq_nr
            )
            self.readout_nco = self.readout_freq_center - readout_if_center
            self.readout_freq_arr = self.readout_nco + self.readout_if_arr

            pls.hardware.set_adc_attenuation(self.sample_port, 0.0)
            pls.hardware.set_dac_current(self.readout_port, DAC_CURRENT)
            pls.hardware.set_dac_current(self.control_port, DAC_CURRENT)
            pls.hardware.set_inv_sinc(self.readout_port, 0)
            pls.hardware.set_inv_sinc(self.control_port, 0)
            pls.hardware.configure_mixer(
                freq=self.readout_nco,
                in_ports=self.sample_port,
                out_ports=self.readout_port,
                sync=False,  # sync in next call
            )
            pls.hardware.configure_mixer(
                freq=self.control_freq,
                out_ports=self.control_port,
                sync=True,  # sync here
            )

            # ************************************
            # *** Setup measurement parameters ***
            # ************************************

            # Setup lookup tables for frequencies
            pls.setup_freq_lut(
                output_ports=self.readout_port,
                group=0,
                frequencies=self.readout_if_arr,
                phases=np.full_like(self.readout_if_arr, 0.0),
                phases_q=np.full_like(self.readout_if_arr, -np.pi / 2),  # HSB
            )
            pls.setup_freq_lut(
                output_ports=self.control_port,
                group=0,
                frequencies=0.0,
                phases=0.0,
                phases_q=0.0,
            )

            # Setup lookup tables for amplitudes
            pls.setup_scale_lut(
                output_ports=self.readout_port,
                group=0,
                scales=self.readout_amp,
            )
            pls.setup_scale_lut(
                output_ports=self.control_port,
                group=0,
                scales=self.control_amp,
            )

            # Setup readout and control pulses
            # use setup_long_drive to create a pulse with square envelope
            # setup_long_drive supports smooth rise and fall transitions for the pulse,
            # but we keep it simple here
            readout_pulse = pls.setup_long_drive(
                output_port=self.readout_port,
                group=0,
                duration=self.readout_duration,
                amplitude=1.0,
                amplitude_q=1.0,
                rise_time=0e-9,
                fall_time=0e-9,
            )
            control_ns = int(
                round(self.control_duration * pls.get_fs("dac"))
            )  # number of samples in the control template
            control_envelope = sin2(control_ns, drag=self.drag)
            control_pulse = pls.setup_template(
                output_port=self.control_port,
                group=0,
                template=control_envelope,
                envelope=True,
            )

            # Setup sampling window
            pls.set_store_ports(self.sample_port)
            pls.set_store_duration(self.sample_duration)

            # ******************************
            # *** Program pulse sequence ***
            # ******************************
            T = 0.0  # s, start at time zero ...
            for ii in range(2):
                if ii > 0:
                    # pi pulse
                    pls.reset_phase(T, self.control_port)
                    pls.output_pulse(T, control_pulse)
                # Readout pulse starts after control pulse
                T += self.control_duration
                pls.reset_phase(T, self.readout_port)
                pls.output_pulse(T, readout_pulse)
                # Sampling window
                pls.store(T + self.readout_sample_delay)
                # Move to next iteration
                T += self.readout_duration
                if ii > 0:
                    pls.next_frequency(T, self.readout_port)
                T += self.wait_delay

            # **************************
            # *** Run the experiment ***
            # **************************
            pls.run(
                period=T,
                repeat_count=self.readout_freq_nr,
                num_averages=self.num_averages,
                print_time=True,
            )
            self.t_arr, self.store_arr = pls.get_store_data()

            # if self.jpa_params is not None:
            #     pls.hardware.set_lmx(0.0, 0.0, self.jpa_params['pump_port'])
            #     pls.hardware.set_dc_bias(0.0, self.jpa_params['bias_port'])

        return self.save()

    def save(self, save_filename: str = None) -> str:
        return super().save(__file__, save_filename=save_filename)

    @classmethod
    def load(cls, load_filename: str) -> "ExcitedSweep":
        with h5py.File(load_filename, "r") as h5f:
            readout_freq_center = h5f.attrs["readout_freq_center"]
            readout_freq_span = h5f.attrs["readout_freq_span"]
            readout_freq_nr = h5f.attrs["readout_freq_nr"]
            control_freq = h5f.attrs["control_freq"]
            readout_amp = h5f.attrs["readout_amp"]
            control_amp = h5f.attrs["control_amp"]
            readout_duration = h5f.attrs["readout_duration"]
            control_duration = h5f.attrs["control_duration"]
            sample_duration = h5f.attrs["sample_duration"]
            readout_port = h5f.attrs["readout_port"]
            control_port = h5f.attrs["control_port"]
            sample_port = h5f.attrs["sample_port"]
            wait_delay = h5f.attrs["wait_delay"]
            readout_sample_delay = h5f.attrs["readout_sample_delay"]
            num_averages = h5f.attrs["num_averages"]
            drag = h5f.attrs["drag"]
            readout_nco = h5f.attrs["readout_nco"]

            # jpa_params = ast.literal_eval(h5f.attrs["jpa_params"])

            readout_freq_arr = h5f["readout_freq_arr"][()]
            readout_if_arr = h5f["readout_if_arr"][()]
            t_arr = h5f["t_arr"][()]
            store_arr = h5f["store_arr"][()]

        self = cls(
            readout_freq_center=readout_freq_center,
            readout_freq_span=readout_freq_span,
            readout_freq_nr=readout_freq_nr,
            control_freq=control_freq,
            readout_amp=readout_amp,
            control_amp=control_amp,
            readout_duration=readout_duration,
            control_duration=control_duration,
            sample_duration=sample_duration,
            readout_port=readout_port,
            control_port=control_port,
            sample_port=sample_port,
            wait_delay=wait_delay,
            readout_sample_delay=readout_sample_delay,
            num_averages=num_averages,
            # jpa_params=jpa_params,
            drag=drag,
        )
        self.readout_freq_arr = readout_freq_arr
        self.readout_if_arr = readout_if_arr
        self.readout_nco = readout_nco
        self.t_arr = t_arr
        self.store_arr = store_arr

        return self

    def analyze(self, all_plots: bool = False):
        assert self.t_arr is not None
        assert self.store_arr is not None
        assert self.readout_freq_arr is not None
        assert self.readout_if_arr is not None
        assert self.readout_nco is not None
        assert len(self.readout_freq_arr) == self.readout_freq_nr
        assert len(self.readout_if_arr) == self.readout_freq_nr

        import matplotlib.pyplot as plt
        from scipy.optimize import curve_fit

        try:
            from resonator_tools import circuit

            _has_resonator_tools = True
        except ImportError:
            _has_resonator_tools = False

        ret_fig = []

        idx = np.arange(IDX_LOW, IDX_HIGH)
        t_low = self.t_arr[IDX_LOW]
        t_high = self.t_arr[IDX_HIGH]
        nr_samples = IDX_HIGH - IDX_LOW

        if all_plots:
            # Plot raw store data for first iteration as a check
            fig1, ax1 = plt.subplots(2, 1, sharex=True, tight_layout=True)
            ax11, ax12 = ax1
            ax11.axvspan(1e9 * t_low, 1e9 * t_high, facecolor="#dfdfdf")
            ax12.axvspan(1e9 * t_low, 1e9 * t_high, facecolor="#dfdfdf")
            ax11.plot(1e9 * self.t_arr, np.abs(self.store_arr[0, 0, :]))
            ax12.plot(1e9 * self.t_arr, np.angle(self.store_arr[0, 0, :]))
            ax12.set_xlabel("Time [ns]")
            fig1.show()
            ret_fig.append(fig1)

        # Analyze
        data = self.store_arr[:, 0, idx]
        data.shape = (self.readout_freq_nr, 2, nr_samples)
        resp_I_arr = np.zeros((2, self.readout_freq_nr), np.complex128)
        resp_Q_arr = np.zeros((2, self.readout_freq_nr), np.complex128)
        dt = self.t_arr[1] - self.t_arr[0]
        t = dt * np.arange(nr_samples)
        for ii, readout_if in enumerate(self.readout_if_arr):
            cos = np.cos(2 * np.pi * readout_if * t)
            sin = np.sin(2 * np.pi * readout_if * t)
            for jj in range(2):
                data_slice = data[ii, jj, :]
                # TODO: low-pass filter the demodulated signal?
                I_real = np.sum(data_slice.real * cos) / nr_samples
                I_imag = -np.sum(data_slice.real * sin) / nr_samples
                resp_I_arr[jj, ii] = I_real + 1j * I_imag
                Q_real = np.sum(data_slice.imag * cos) / nr_samples
                Q_imag = -np.sum(data_slice.imag * sin) / nr_samples
                resp_Q_arr[jj, ii] = Q_real + 1j * Q_imag

        _, resp_H_arr = untwist_downconversion(resp_I_arr, resp_Q_arr)
        resp_dB = 20 * np.log10(np.abs(resp_H_arr))
        resp_phase = np.angle(resp_H_arr)
        # resp_phase *= -1
        resp_phase = np.unwrap(resp_phase, axis=-1)
        N = self.readout_freq_nr // 4
        idx = np.zeros(self.readout_freq_nr, bool)
        idx[:N] = True
        idx[-N:] = True
        pfit_g = np.polyfit(self.readout_freq_arr[idx], resp_phase[0, idx], 1)
        pfit_e = np.polyfit(self.readout_freq_arr[idx], resp_phase[1, idx], 1)
        pfit = 0.5 * (pfit_g + pfit_e)
        background = np.polyval(pfit, self.readout_freq_arr)
        resp_phase[0, :] -= background
        resp_phase[1, :] -= background
        separation = np.abs(resp_H_arr[1, :] - resp_H_arr[0, :])

        p0 = [
            self.readout_freq_arr[np.argmax(separation)],
            1 / self.readout_duration,
            np.max(separation),
            0.0,
        ]
        popt, pcov = curve_fit(_gaussian, self.readout_freq_arr, separation, p0)

        print("----------------")
        if _has_resonator_tools:
            port_g = circuit.notch_port(
                self.readout_freq_arr, resp_H_arr[0, :] * np.exp(-1j * background)
            )
            port_e = circuit.notch_port(
                self.readout_freq_arr, resp_H_arr[1, :] * np.exp(-1j * background)
            )
            port_g.autofit()
            port_e.autofit()

            f_g = port_g.fitresults["fr"]
            f_e = port_e.fitresults["fr"]
            f_r = (f_e + f_g) / 2
            f_o = popt[0]
            chi_hz = (f_e - f_g) / 2
            print(f"ω_g / 2π = {f_g * 1e-9:.6f} GHz")
            print(f"ω_e / 2π = {f_e * 1e-9:.6f} GHz")
            print(f"ω_r / 2π = {f_r * 1e-9:.6f} GHz")
            print(f"χ / 2π = {chi_hz * 1e-3:.2f} kHz")
        print(f"ω_opt / 2π = {f_o * 1e-9:.6f} GHz")
        print("----------------")

        fig2, ax2 = plt.subplots(3, 1, sharex=True, tight_layout=True, figsize=(6.4, 6.4))
        ax21, ax22, ax23 = ax2

        for ax_ in ax2:
            if _has_resonator_tools:
                ax_.axvline(1e-9 * f_g, ls="--", c="tab:red", alpha=0.5)
                ax_.axvline(1e-9 * f_e, ls="--", c="tab:purple", alpha=0.5)
            ax_.axvline(1e-9 * popt[0], ls="--", c="tab:brown", alpha=0.5)

        ax21.plot(1e-9 * self.readout_freq_arr, resp_dB[0, :], c="tab:blue", label="|g>")
        ax21.plot(1e-9 * self.readout_freq_arr, resp_dB[1, :], c="tab:orange", label="|e>")
        ax22.plot(1e-9 * self.readout_freq_arr, resp_phase[0, :], c="tab:blue")
        ax22.plot(1e-9 * self.readout_freq_arr, resp_phase[1, :], c="tab:orange")
        ax23.plot(
            1e-9 * self.readout_freq_arr, 1e3 * separation, c="tab:green", label="||e> - |g>|"
        )

        if _has_resonator_tools:
            ax21.plot(
                1e-9 * port_g.f_data,
                20 * np.log10(np.abs(port_g.z_data_sim)),
                c="tab:red",
                ls="--",
            )
            ax21.plot(
                1e-9 * port_e.f_data,
                20 * np.log10(np.abs(port_e.z_data_sim)),
                c="tab:purple",
                ls="--",
            )
            ax22.plot(1e-9 * port_g.f_data, np.angle(port_g.z_data_sim), c="tab:red", ls="--")
            ax22.plot(1e-9 * port_e.f_data, np.angle(port_e.z_data_sim), c="tab:purple", ls="--")

        ax23.plot(
            1e-9 * self.readout_freq_arr,
            1e3 * _gaussian(self.readout_freq_arr, *popt),
            c="tab:brown",
            ls="--",
        )

        ax21.set_ylabel("Amplitude [dBFS]")
        ax22.set_ylabel("Phase [rad]")
        ax23.set_ylabel("Separation [mFS]")
        ax2[-1].set_xlabel("Readout frequency [GHz]")
        ax21.legend(ncol=2, loc="lower right")
        ax23.legend(loc="upper right")
        fig2.show()
        ret_fig.append(fig2)

        return ret_fig


def _gaussian(x, x0, s, a, o):
    return a * np.exp(-0.5 * ((x - x0) / s) ** 2) + o
