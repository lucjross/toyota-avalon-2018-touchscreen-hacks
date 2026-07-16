# ICL7660-Based Unregulated VGL (-9.5V to -9.8V) Generator

This document lists the required components and details the schematic for building a simplified, **Unregulated VGL (-9.5V to -9.8V) Generator** using the **ICL7660** charge-pump inverter (or a relabeled/counterfeit LT1054 chip that lacks regulation).

By powering the chip's input directly from the regulated **AVDD (+10.0V)** rail, we bypass the need for any regulation feedback loop. The chip acts as a simple 1:1 voltage inverter, producing a stable VGL output of approximately **-9.5V to -9.8V** (due to the chip's internal voltage drop) which is ideal for the gate driver low rail.

---

## 1. Complete Bill of Materials (BOM)

To build this circuit, you will need the following parts:

| Qty | Component | Value / Rating | Purpose |
|---|---|---|---|
| 1 | **ICL7660 IC** | DIP-8 package | Switched-capacitor voltage inverter |
| 1 | **Schottky Diode (D1)** | **1N5819** (or 1N5817) | Prevents latch-up at startup |
| 1 | **Electrolytic Cap (C_IN)** | **10µF** (>= 16V) | Input bypass filter |
| 1 | **Electrolytic Cap (C1)** | **22µF** (>= 16V) | Flying charge-pump capacitor |
| 1 | **Electrolytic Cap (C_OUT)**| **100µF** (>= 16V) | Output reservoir filter |

---

## 2. Circuit Schematic

```
                            AVDD (+10.0V) Regulated Input
                                 │
                 ┌───────────────┼─────────────────┐
                 │               │ (Pin 8: VIN)    │
                 │             ┌─┴─────────┐       │
                 │             │  ICL7660  │       │
            [+] C_IN [─]       │  (DIP-8)  │       │
               (10µF)           │           │       │
                 │             │1     NC   │ (Open)│
                 ▼             │           │       │
             System GND        │2     CAP+ ├─┐     │
                               │           │ │     │
                               │4     CAP- ├─┼─┐   │
                               │           │ │ │   │
            System GND ────────┤3     GND  │ │ │   │
                               │           │ │ │   │
                               │6     NC   │ │ │ (Open)
                               │           │ │ │   │
                               │5     VOUT ├─┼─┼─┬─┘
                               └───────────┘ │ │ │
                                             │ │ │
                                             │ └─┼─►[+] C1 [─] (22µF)
                                             │   │   (Flying Cap)
                                             │   ▼
                                             │ System GND
                                             │
                                             ├─────────[─] C_OUT [+] ──► System GND (0V)
                                             │           (100µF)
                                             │
                                             └───◄[ Anode ] Schottky D1 (1N5819)
                                                            [ Cathode ] ──► System GND (0V)
                                             │
                                             ▼
                                         VGL Output
                                       (-9.5V to -9.8V)
```

---

## 3. Wiring Connections (Pin by Pin)

* **Pin 1 (NC/Boost):** Leave open (unconnected).
* **Pin 2 (CAP+):** Connect to the **positive (+) lead** (longer leg) of the **22µF capacitor (C1)**.
* **Pin 3 (GND):** Connect directly to **System GND (0V)**.
* **Pin 4 (CAP-):** Connect to the **negative (-) lead** (shorter leg) of the **22µF capacitor (C1)**.
* **Pin 5 (VOUT):** Connect to:
    *   The **negative (-) lead** (shorter leg) of the **100µF capacitor (C_OUT)** *(connect the positive (+) lead of C_OUT to System GND)*.
    *   The **Anode (non-striped side)** of the **1N5819 Schottky diode (D1)** *(connect the Cathode/striped side of D1 to System GND)*.
    *   **This pin is your VGL (-9.5V to -9.8V) rail.**
* **Pin 6 (NC/LV):** Leave open (unconnected). Since VIN (+10V) is greater than 3.5V, this pin must remain open.
* **Pin 7 (OSC):** Leave open (unconnected).
* **Pin 8 (VIN):** Connect to your **AVDD (+10.0V)** supply and the **positive (+) lead** (longer leg) of the **10µF capacitor (C_IN)** *(negative (-) lead of C_IN goes to System GND)*.

---

## 4. Why This Works
The ICL7660 functions as a highly efficient charge-pump voltage inverter. It operates by charging the flying capacitor ($C1$) to the input voltage ($V_{IN}$) during the first half of the internal clock cycle, and then connecting it in reverse across the output capacitor ($C_{OUT}$) during the second half of the cycle. 

Because we feed it $V_{IN} = \text{AVDD} = +10.0\text{V}$, the output is:
$$V_{OUT} = -V_{IN} + V_{drop}$$

Under the very low current load of the gate driver VGL rail ($<1\text{mA}$), the internal switch resistance drops the voltage slightly to provide exactly **-9.5V to -9.8V** at the output, eliminating the need for feedback resistors or active regulation.
