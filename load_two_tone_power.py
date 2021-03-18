# -*- coding: utf-8 -*-
"""
Loader for files saved by two_tone_power.py
Copyright (C) 2021  Intermodulation Products AB.

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see
<https://www.gnu.org/licenses/>.
"""
import h5py
from matplotlib import rcParams
import matplotlib.pyplot as plt
import numpy as np
rcParams['figure.dpi'] = 108.8

LOGSCALE = False  # Plot response in logarithmic scale (dBFS), both in colormap and line cut.
LINECUT = False  # Plot an horizontal line cut of the 2D sweep. Interactive.
BLIT = True  # Use blitting when plotting. Faster if it works.
AMP_IDX = 0  # internal use

load_filename = "data/two_tone_power_20210301_084047.h5"
load_filename = "data/two_tone_power_20210304_090631.h5"


def load(load_filename):
    with h5py.File(load_filename, "r") as h5f:
        df = h5f.attrs["df"]
        dither = h5f.attrs["dither"]
        input_port = h5f.attrs["input_port"]
        cavity_port = h5f.attrs["cavity_port"]
        qubit_port = h5f.attrs["qubit_port"]
        cavity_amp = h5f.attrs["cavity_amp"]
        cavity_freq = h5f.attrs["cavity_freq"]
        qubit_freq_arr = h5f["qubit_freq_arr"][()]
        qubit_amp_arr = h5f["qubit_amp_arr"][()]
        resp_arr = h5f["resp_arr"][()]
        source_code = h5f["source_code"][()]

    nr_amps = len(qubit_amp_arr)

    global AMP_IDX
    AMP_IDX = nr_amps // 2

    if LOGSCALE:
        data = 20. * np.log10(np.abs(resp_arr))
    else:
        data = np.abs(resp_arr)
        data_max = data.max()
        unit = ""
        if data_max < 1e-6:
            unit = "n"
            data *= 1e9
        elif data_max < 1e-3:
            unit = "μ"
            data *= 1e6
        elif data_max < 1e0:
            unit = "m"
            data *= 1e3
    amp_dBFS = 20 * np.log10(qubit_amp_arr / 1.0)

    # choose limits for colorbar
    cutoff = 1.  # %
    lowlim = np.percentile(data, cutoff)
    highlim = np.percentile(data, 100. - cutoff)

    # extent
    x_min = 1e-9 * qubit_freq_arr[0]
    x_max = 1e-9 * qubit_freq_arr[-1]
    dx = 1e-9 * (qubit_freq_arr[1] - qubit_freq_arr[0])
    y_min = amp_dBFS[0]
    y_max = amp_dBFS[-1]
    dy = amp_dBFS[1] - amp_dBFS[0]

    if LINECUT:
        fig1 = plt.figure(tight_layout=True, figsize=(6.4, 9.6))
        ax1 = fig1.add_subplot(2, 1, 1)
    else:
        fig1 = plt.figure(tight_layout=True, figsize=(6.4, 4.8))
        ax1 = fig1.add_subplot(1, 1, 1)
    im = ax1.imshow(
        data,
        origin='lower',
        aspect='auto',
        interpolation='none',
        extent=(x_min - dx / 2, x_max + dx / 2, y_min - dy / 2, y_max + dy / 2),
        vmin=lowlim,
        vmax=highlim,
    )
    if LINECUT:
        line_sel = ax1.axhline(amp_dBFS[AMP_IDX], ls="--", c="k", lw=3, animated=BLIT)
    ax1.set_title(f"Probe frequency: {cavity_freq/1e9:.2f} GHz")
    ax1.set_xlabel("Pump frequency [GHz]")
    ax1.set_ylabel("Pump amplitude [dBFS]")
    cb = fig1.colorbar(im)
    if LOGSCALE:
        cb.set_label("Response amplitude [dBFS]")
    else:
        cb.set_label(f"Response amplitude [{unit:s}FS]")

    if LINECUT:
        ax2 = fig1.add_subplot(4, 1, 3)
        ax3 = fig1.add_subplot(4, 1, 4, sharex=ax2)

        line_a, = ax2.plot(1e-9 * qubit_freq_arr, data[AMP_IDX], animated=BLIT)
        line_fit_a, = ax2.plot(1e-9 * qubit_freq_arr, np.full_like(qubit_freq_arr, np.nan), ls="--", animated=BLIT)
        line_p, = ax3.plot(1e-9 * qubit_freq_arr, np.angle(resp_arr[AMP_IDX]), animated=BLIT)
        line_fit_p, = ax3.plot(1e-9 * qubit_freq_arr, np.full_like(qubit_freq_arr, np.nan), ls="--", animated=BLIT)

        f_min = 1e-9 * qubit_freq_arr.min()
        f_max = 1e-9 * qubit_freq_arr.max()
        f_rng = f_max - f_min
        a_min = data.min()
        a_max = data.max()
        a_rng = a_max - a_min
        p_min = -np.pi
        p_max = np.pi
        p_rng = p_max - p_min
        ax2.set_xlim(f_min - 0.05 * f_rng, f_max + 0.05 * f_rng)
        ax2.set_ylim(a_min - 0.05 * a_rng, a_max + 0.05 * a_rng)
        ax3.set_xlim(f_min - 0.05 * f_rng, f_max + 0.05 * f_rng)
        ax3.set_ylim(p_min - 0.05 * p_rng, p_max + 0.05 * p_rng)

        ax3.set_xlabel("Frequency [GHz]")
        if LOGSCALE:
            ax2.set_ylabel("Response amplitude [dB]")
        else:
            ax2.set_ylabel(f"Response amplitude [{unit:s}FS]")
        ax3.set_ylabel("Response phase [rad]")

        def onbuttonpress(event):
            if event.inaxes == ax1:
                global AMP_IDX
                AMP_IDX = np.argmin(np.abs(amp_dBFS - event.ydata))
                update()

        def onkeypress(event):
            global AMP_IDX
            if event.inaxes == ax1:
                if event.key == "up":
                    AMP_IDX += 1
                    if AMP_IDX >= len(amp_dBFS):
                        AMP_IDX = len(amp_dBFS) - 1
                    update()
                elif event.key == "down":
                    AMP_IDX -= 1
                    if AMP_IDX < 0:
                        AMP_IDX = 0
                    update()

        def update():
            global AMP_IDX
            line_sel.set_ydata([amp_dBFS[AMP_IDX], amp_dBFS[AMP_IDX]])
            # ax1.set_title(f"amp = {amp_arr[AMP_IDX]:.2e}")
            print(f"drive amp {AMP_IDX:d}: {qubit_amp_arr[AMP_IDX]:.2e} FS = {amp_dBFS[AMP_IDX]:.1f} dBFS")
            line_a.set_ydata(data[AMP_IDX])
            line_p.set_ydata(np.angle(resp_arr[AMP_IDX]))
            line_fit_a.set_ydata(np.full_like(qubit_freq_arr, np.nan))
            line_fit_p.set_ydata(np.full_like(qubit_freq_arr, np.nan))
            # ax2.set_title("")
            if BLIT:
                global bg
                fig1.canvas.restore_region(bg)
                ax1.draw_artist(line_sel)
                ax2.draw_artist(line_a)
                ax3.draw_artist(line_p)
                fig1.canvas.blit(fig1.bbox)
                # fig1.canvas.flush_events()
            else:
                fig1.canvas.draw()

        fig1.canvas.mpl_connect('button_press_event', onbuttonpress)
        fig1.canvas.mpl_connect('key_press_event', onkeypress)

    fig1.show()
    if LINECUT and BLIT:
        fig1.canvas.draw()
        # fig1.canvas.flush_events()
        global bg
        bg = fig1.canvas.copy_from_bbox(fig1.bbox)
        ax1.draw_artist(line_sel)
        ax2.draw_artist(line_a)
        ax3.draw_artist(line_p)
        fig1.canvas.blit(fig1.bbox)

    return fig1


if __name__ == "__main__":
    fig1 = load(load_filename)
