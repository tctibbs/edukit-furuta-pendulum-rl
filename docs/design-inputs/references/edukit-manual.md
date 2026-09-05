# UCLA Edukit Manual and tutorials

Prof. William J. Kaiser, UCLA Samueli School of Engineering, hosts the authoritative educational material for this kit. That material carries the validated dynamic model.

Site: <https://sites.google.com/view/ucla-st-motor-control/home>

Contact: kaiser@ee.ucla.edu

| Local file | Document | Size | Link |
|---|---|---|---|
| `Edukit_Manual.pdf` | Edukit Manual, current revision | 173 pages | [Drive](https://drive.google.com/file/d/1TShSZnhovXGBWyp9U5gxpYn494UExrGA/view) |
| `Serial_Interface_Guide.pdf` | Serial control interface | 19 pages | [Drive](https://drive.google.com/file/d/1gxOZJ68nM6F8RLyT5_11yhetiQPhkdwl/view) |
| `RealTime_Workbench_Guide.pdf` | Real Time Control System Workbench | 12 pages | [Drive](https://drive.google.com/file/d/1IK0jC-gvZcKVLdc7yAyQ-cKuVbFzp-tr/view) |
| `Assembly_with_soldering.pdf` | Assembly video index, soldered path | 1 page | [Drive](https://drive.google.com/file/d/15bxHCpIVDkShvDSBV-TKK1VoyA9-v4Z1/view) |
| `Assembly_no_soldering.pdf` | Assembly video index, solderless path | 2 pages | [Drive](https://drive.google.com/file/d/1WjKFYuabeHYK_HCCIp5l3CJ5ZwTb3bSU/view) |
| `Install_Firmware.pdf` | Firmware install and first startup | 25 pages | [Drive](https://drive.google.com/file/d/1viemIrpEuDAfWZSLzvkyF_2NQqDRg5Az/view) |
| `Edukit_firmware.bin` | Prebuilt firmware image, STM32 raw binary | 127 KB | [Drive](https://drive.google.com/file/d/1zVwDdAiL3QSQ81GxXas_2DFtwxWzJHig/view) |
| `STM32CubeIDE_project.zip` | Full firmware source project | 24 MB | [Drive](https://drive.google.com/file/d/1I-F9KUY2dun79LGVkVu25ZPb_Rtbx5q7/view) |

The site also carries a second install guide for a different host platform, and Manual Rev. 2.0, dated 2021-01-12, superseded by the current 173-page revision.

## Highlights

| Section | Page | What |
|---|---|---|
| Sec. 4, Table 2 | 11 | System characteristics, gains, resolutions |
| App. D, Pendulum Dynamics | 143 | The validated dynamic model |
| App. E, Rotor Actuator Plant with Acceleration Control | 150 | The `apply_acceleration()` actuator model |
| App. F, Rotor Actuator Plant Transfer Function | 164 | Closed-form rotor plant |
| Sec. 14 and 15, LQR | | Baseline gains for inverted and suspended mode |
| App. D, Serial Control Interface | 121 | Command set for a host-side gym wrapper |
| App. B, Real Time Workbench | 111 | 500 Hz logging path for system identification |
| App. G, Pendulum Angle Error Autocompensation | 172 | Tilt calibration |

## Course tutorials, 14 chapters

Linked from the site at the top of this page. Chapters 1 to 8 cover classical frequency-response and root-locus design, 9 to 14 cover full state feedback and LQR, and 12 automates tilt calibration. Chapters 13 and 14 apply LQR to suspended and inverted mode. They're the direct baselines to compare against.

## Firmware source

<https://github.com/wjkaiser/Edukit_Rotary_Inverted_Pendulum_Project>
