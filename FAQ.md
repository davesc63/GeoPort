# GeoPort - FAQ
Current Version: v1.0.2

# What's new
- Notifications!
- Receive a notification with the status of Set and Clear location
- Updated error messages in the terminal window with troubleshooting steps and link to Github issues

<img src="https://github.com/davesc63/GeoPort/blob/main/images/geoport-notifications-demo.gif">



## How to use Mac version

- Download .zip file from the **"Assets"** section below
- Extract zip file - contains run.sh and GeoPort executable
- ensure run.sh is executable `chmod +x run.sh`
- `./run.sh`

## Troubleshooting

- Ensure you run the app as Administrator (Windows) or sudo (Mac)
- On Windows, the Administrator prompt is automatic
- On Mac, `run.sh` will execute GeoPort as `sudo`

### Mac Specific
It seems like on MacOS Sonoma (my machine), GeoPort will not run properly when it is executed from the `Downloads` folder
Extract the zip outside of the Downloads folder, like into `/Users/username/GeoPort` and it will run fine!

**Connection Timeouts**: If you get this on Mac there are two possible knowns reasons:
1) You are running GeoPort from your `Downloads` folder<br>
   **FIX:** Move GeoPort to somewhere else, such as your `Home` or `Desktop` and run again
2) You are not running with `sudo` permissions<br>
   **FIX:** Execute the `run.sh` file, or in a terminal window in the folder containing GeoPort type: `sudo GeoPort`

### Windows Specific

If you are running as administrator and receive `Unable to create tunnel within timeout` there is most likely a Windows firewall issue. When GeoPort runs for the first time, you receive a network access prompt when the tunnel adapter is created. In some cases, only a single option is selected. You need to select both **Public** and **Private** networks.

If GeoPort is already installed, you can change this setting by going into:
- `Control Panel - System and Security`
- Select `Allow an app through Windows Firewall`
- Select `Change settings`
- Scroll down to the entry for `GeoPort`
- Your options here are:

1. Allow both `Public` and `Private`
2. Delete the entry for GeoPort. Re-run GeoPort and when prompted to allow connects - select both checkboxes

<img src="https://github.com/davesc63/GeoPort/blob/main/images/geoport-win-fw1.png"></img>
### Figure 1 - Windows Firewall in Control Panel


<img src="https://github.com/davesc63/GeoPort/blob/main/images/geoport-win-fw2.png"></img>
### Figure 2 - Windows firewall incoming rules

<img src="https://github.com/davesc63/GeoPort/blob/main/images/geoport-win-fw3.png"></img>
### Figure 3 - Network adapter pop-up on first run

### Known issues
- Windows multi-device support. You can connect a single device to simulate location. If you wish to choose another device. You will need to close down GeoPort and run it again. This is not vital functionality but something I am looking to resolve. Unfortunately it's the way the "wintun" driver is behaving.

On the positive side - multi-device support on Mac is amazing and with a little update in v1.0.2, it is incredibly fast and efficient to switch between different devices!

- Older versions of MacOS (Catalina) may not be supported by the version of Python used within GeoPort. This isn't a problem wtih GeoPort, moreso it's the supported versions provided by python.org
  Your options are to upgrade your MacOS to > v11

### Supported iOS
All - iOS 17 and below

### Supported OS
Windows 64-bit
MacOS ARM
MacOS Intel
