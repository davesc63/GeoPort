# GeoPort: Your Location, Anywhere! 🌍 


<p align="center">
  
  <a href="https://www.buymeacoffee.com/davesc63">
    <img src="https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20beer&emoji=🍺&slug=davesc63&button_colour=FFDD00&font_colour=000000&outline_colour=000000&coffee_colour=ffffff" alt="Buy me a beer">
  </a><br> https://geoport.me
</p>


[![Join Discord](https://img.shields.io/badge/Discord-Join%20Us-7289DA?logo=discord&style=for-the-badge)](https://discord.gg/genRca55Nb)<br>
<a href="https://github.com/davesc63/GeoPort/releases/tag/v4.0.2">Release Notes and Downloads</a><br><p>
<a href="https://github.com/davesc63/GeoPort/blob/main/FAQ.md">Need Help? - FAQ</a><br><p>
<a href="https://www.surveymonkey.com/r/BLQ8M75">Your feedback helps - Fill out the Survey</a>

<p align="center"><strong>GeoPort needs your help.</p></strong> </p>
Please consider <strong>donating</strong> and supporting the project. Your support helps to grow the platform and features.<br><p></p><br><p></p>


Immerse yourself in a world of possibilities with **GeoPort**, the ultimate location simulation app. GeoPort allows you to take control of your virtual presence, letting you be anywhere on the globe at the touch of a button. Whether you want to explore distant cities, surprise friends with exotic check-ins, or test location-based apps, GeoPort is your passport to a limitless world.



## Key Features

- **Global Presence**
Spoof your location and appear as if you're in any city, country, or landmark globally.

- **Explore with Ease**
Experience the thrill of virtual travel without leaving your comfort zone. Wander the streets of Tokyo, relax on a beach in Bali, or stroll through the historic alleys of Rome—all from the palm of your hand.

- **Test Apps Effectively**
Developers, take note! GeoPort is your go-to tool for testing location-based features in your apps. Simulate diverse scenarios effortlessly.

- **Privacy and Security**
Your privacy matters. GeoPort ensures a secure experience, allowing you to control when and where your virtual self appears.

- **User-Friendly Interface**
Seamlessly navigate GeoPort's intuitive interface. Set your desired location with a few taps and teleport within seconds.

- **Unleash Your Imagination with GeoPort!**
Download now and elevate your location experience beyond boundaries. Teleportation has never been this easy—**GeoPort**, where every location is just a click away!

<p align="center">
  <img src="https://raw.githubusercontent.com/davesc63/GeoPort/main/images/geoport2.png" alt="geoport" width="50%"><br><br>
   <img src="https://raw.githubusercontent.com/davesc63/GeoPort/main/images/geoport-demo.gif" alt="geoport">
</p>

## Fuel Mode:

For the :australia: Aussies :australia: who love to fire up their choppers and get their *Frugal Fuels* from the KwikiMart.
the **"Fuel"** mode of GeoPort to easily select the best prices across Australia! There is even the ability to select **state-based** pricing

<p align="center">
<img src="https://github.com/davesc63/GeoPort/blob/main/images/fuel.png" alt="fuel" width="50%">
</p>

## Developer Mode

**Developer Mode:** Enable developer mode on connected iOS devices.

They've made it harder to enable Developer Mode, but GeoPort handles it with ease. If you don't have Developer Mode enabled on your iOS device - you will need to temporarily remove your passcode to allow GeoPort to enable Developer Mode (Don't worry, GeoPort will let you know when running the app)
<p align="center">
<img src="https://github.com/davesc63/GeoPort/blob/main/images/devmode.png" alt="devmode" width="50%">
</p>

**Passcode Handling**
<p align="center">
<img src="https://github.com/davesc63/GeoPort/blob/main/images/passcode.png" alt="passcode" width="50%">
</p>



## Prerequisites

An iOS device and a sense of adventure!
*That's Right* - you do not need to install complex apps like python for **GeoPort** to work

**Windows Users**
You will need to install iTunes (we need their USB service so we can discover the iOS device!)

## Installation

- [Download](https://github.com/davesc63/GeoPort/releases/) the package for your operating system
- Run the application
- Explore the world and **Simulate Location**

## Running from source

Prefer to run the code yourself (or contribute)? The source is fully
functional and includes the extra features listed below:

```bash
git clone https://github.com/davesc63/GeoPort.git
cd GeoPort
pip install -r requirements.txt
python src/main.py
```

**Python 3.10 – 3.12 required** (3.13 is not supported yet: the `lzfse` C
extension has no cp313 Windows wheel).

The web UI opens at `http://localhost:54321` (a random high port is used if
that one is busy). A few extra switches are available:

- `--no-browser` - don't auto-open the browser
- `--port <n>` - pick the web port
- `--wifihost <ip>` / `--udid <udid>` - target a specific device over Wi-Fi
- `--restart-remoted` - stop/restart the Apple `remoted` service around
  tunnels on macOS. **Off by default** because it can break Xcode's device
  connection (issue #44).

> **Tip (issue #44):** if you also use Xcode to deploy to the same iPhone,
> leave `--restart-remoted` off. Disconnecting from GeoPort now releases the
> tunnel cleanly so Xcode can connect again.

### Features in the source build beyond the release exe

- **Server-side route/GPX playback** - the Play button now sends the route to
  the server, which walks it at the selected speed (walk/run/ride/drive) with
  one tunnel session for the whole route. Pause holds the last point; Stop
  clears the device location. Progress: `/route_status`.
- **Refresh-proof state** - refreshing the page keeps the connection, the
  simulated location (marker + coordinates) and the spoof buttons. A
  "connection lost" banner with one-click reconnect appears if the tunnel
  drops.
- **Saved location presets** - the Save button next to the location field
  stores names in `~/.geoport/locations.json`; the dropdown loads them.
- **Live activity log** - expand "Activity log" at the bottom of the page to
  tail `GeoPort.log` in the browser.
- **Dark mode is the default** (your choice is remembered).
- **System tray icon** - a map-pin in the notification area shows live
  status (connected / spoofing / walking route), with *Open GeoPort* and
  *Quit* (best effort: `pystray` is optional at runtime).
- **No telemetry** - the `api.geoport.me` phone-home calls are gone.
- **Localhost-only + optional API token** - the app binds to 127.0.0.1 (the
  old build listened on 0.0.0.0 with the debug console enabled). Set the
  `GEOPORT_TOKEN` env var to require a token on mutating API calls.
- **API + tests** - see `API.md` for the full HTTP API (drive it from
  scripts/Shortcuts) and `tests/test_smoke.py` (run with `pytest`).

## App Notes
- iOS 17 & iOS 18 are supported on both Windows and Mac
- Administrator / Sudo permissions are required for iOS17
- If you forget to reset your location when you disconnect, Don't worry! Simply connect your device again and "Stop Location"

## Tech Stuff and recognition
GeoPort is built with python, flask and pymobiledevice3
Interface inspired by the popular iFakeLocation, GeoPort is built for familiarity with the addition of iOS17 and Windows support (Windows release imminent)

Pymobiledevice3 - https://github.com/doronz88/pymobiledevice3<br>
iFakeLocation - https://github.com/master131/iFakeLocation

## Keywords
iOS 17, location spoofing, ios17 location simulation, ios17 windows support<br>
iOS 18, location spoofing, ios18 location simulation, ios18 windows support


## Pay it forward
If this tools helps you, please consider buying me a beer so I can keep this app going!<br>
<p align="center">
  <a href="https://www.buymeacoffee.com/davesc63">
    <img src="https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20beer&emoji=🍺&slug=davesc63&button_colour=FFDD00&font_colour=000000&outline_colour=000000&coffee_colour=ffffff" alt="Buy me a beer">
  </a>
</p>
