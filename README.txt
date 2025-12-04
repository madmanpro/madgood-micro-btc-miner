MADGood Micro BTC Miner
I move — therefore the universe must respond.
OZUWA Block


Ui for the cpuminer-opt engine
for future development and products you can donate to the cause at this address.
bc1qkjdpk5awqwswx7rl4nclh90x8gntm93g3y4mnc
THANK YOU!

*Lightweight Solo Bitcoin Miner — Powered by MADGood Radio & the MADGood Creative Network*

**Version:** 0.1.0
**Backend:** cpuminer-opt
**Pool:** solo.ckpool.org
**Author:** Corey Marshall (MADGood Radio / MADGood Labs)

----------------------------------------------------------------------------------------------

**Overview**

The MADGood Micro Miner, is a desktop application that turns any laptop or computer into a lightweight solo Bitcoin miner. It provides a clean graphical interface, real-time mining stats, connection status indicators, power controls, and a built-in log viewer. This miner uses 'cpuminer-opt' under the hood and connects directly to 'CKPool', a zero-fee solo mining pool. Every hash produced is a real chance to hit a Bitcoin block — a digital lottery ticket created in real time.


**Features**

One-Click Mining:
* Start or stop mining instantly.
* No terminal commands required.

**Live Dashboard**

Displays:

* Current hashrate
* Total hashes attempted
* BTC price (USD)
* Current block height
* CKPool user ID
* Current job ID
* Mining uptime
* Connectivity & mining status lights

**Built-In Log Window**

View all cpuminer output directly in the app.
Shows:

* job updates
* stratum events
* hashrate reports
* errors
* network changes

**Mining Power Control**

Choose how much CPU to use:

* High (max cores)
* Medium (half cores)
* Low (single-thread mode)

**Block Attempt Counter**

Shows:

* How many jobs you’ve received
* How many blocks you’ve found
  (Blocks found will almost always be 0 — until you hit that golden one.)

**Wallet Locking**

Once you start mining, the wallet address field locks to prevent accidental changes.

**Tabbed Interface**

* Miner Tab: Live dashboard + controls
* Info Tab: Version info + README display

--------------------------------------------------------------------------------------

## **Installation**

1. Place all files in a single folder, e.g.:

   ```
   MMMx/
   ├── madgood_minerx.py
   ├── cpuminer
   ├── BTC Miner App.gif
   └── README.txt
   ```

2. Make sure the cpuminer binary is executable:

   ```bash
   chmod +x cpuminer
   ```

3. Launch the app:

   ```bash
   python3 madgood_minerx.py
   ```

---

## **How Solo Mining Works**

Every hash your miner produces is a **unique guess** at a winning Bitcoin block.

* Most miners run trillions of guesses per second
* A CPU miner produces thousands to millions
* But every guess is still valid
* You can win purely by luck

The odds are extremely low — but never zero.
The MADGood Micro Miner is designed as a **digital golden ticket machine**.

---

## **CKPool Notes**

* You do *not* need an account
* Your Bitcoin address is your username
* CKPool assigns a new session ID each time you connect
* There are no fees
* Rewards go straight to your BTC address if you hit a block

---

## **FAQ**

### **Q: Is this profitable?**

No.
This miner exists for **fun**, learning, and the *small but real* chance of hitting a block.

### **Q: Will stopping and restarting hurt my chances?**

No.
Each hash is an independent lottery ticket.
Stopping simply pauses the guessing.

### **Q: Do I need a share before I can win a block?**

No.
Shares don’t matter for solo mining — you can win without ever submitting one.

---

## **Planned Features**

* Animated GIF support
* MADGood Radio streaming tab
* Windows/macOS/Linux packaged builds
* Session history tracking
* Notification system for block discovery
* Auto-updater

---

## **License**

Created by Corey Marshall for MADGood Radio / MADGood Labs.
For personal, educational, and experimental use only.

Every hash your miner produces is just as valid, just as powerful,
and just as capable of winning a block as the hashes produced by
the biggest mining farm on Earth. You simply produce fewer of them.

