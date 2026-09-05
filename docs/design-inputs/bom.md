# Bill of materials for the STEVAL-EDUKIT01 rotary inverted pendulum

Hardware under test. Quantities and part descriptions are from version 2 of the official ST bill of materials. Electrical context is from the ST product page and from the Edukit Manual, Rev. 3, 173 pp.

## Electronics

| # | Item | Qty | Order code | Notes |
|---|---|---|---|---|
| E1 | Microcontroller development board | 1 | NUCLEO-F401RE | STM32F401RE, Cortex-M4F @ 84 MHz, onboard ST-LINK/V2-1 |
| E2 | Stepper driver expansion board | 1 | X-NUCLEO-IHM01A1 | L6474PD microstepping driver, stacks on E1 |
| E3 | Stepper motor | 1 | Custom (GH) | 12 V, 0.8 A, 10 W. NEMA-17 form factor, 200 full steps/rev per the manual |
| E4 | Rotary encoder | 1 | Custom (GH) | LPD3806-600BM-G5-24C per the manual. 600 PPR, 2400 counts/rev after 4x decode, NPN open collector, 5 to 24 V |
| E5 | Power supply | 1 | Any | 12 V, 1 A, 12 W |
| E6 | Stepper motor cable | 1 | Any | |
| E7 | USB cable, Type-A to Mini-B | 1 | n/a | ST-LINK programming, power, and the 230400 baud serial link. Not itemized in the ST bill of materials |

## Mechanical

| # | Item | Qty | Order code |
|---|---|---|---|
| M1 | Acrylic base | 1 | Custom (GH) |
| M2 | Acrylic motor support | 1 | Custom (GH) |
| M3 | Acrylic vertical strut | 4 | Custom (GH) |
| M4 | Aluminum motor flange | 1 | Custom (GH) |
| M5 | Aluminum L-bracket | 1 | Custom (GH) |
| M6 | Flange for L-bracket support | 1 | Custom (GH) |
| M7 | Pendulum L-shaped tube | 1 | Custom (GH) |
| M8 | Pendulum counterweight | 1 | Custom (GH) |
| M9 | Rubber grommets | 4 | Any |
| M10 | Standoff | 3 | Any |

## Fasteners

| Item | Qty | Use |
|---|---|---|
| M3 x 16 mm pan head screw | 19 | General frame assembly |
| M3 hex nut | 19 | General frame assembly |
| M3 x 10 mm pan head screw | 4 | Motor support |
| M3 x 8 mm pan head screw | 3 | Rotary encoder |
| M2.5 x 6 mm pan head screw | 4 | L-bracket |
| M3 x 6 mm set screw | 2 | Shaft couplings |
