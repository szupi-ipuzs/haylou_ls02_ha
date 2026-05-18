# Haylou LS02 Watch - Home Assistant Integration

This is a Home Assistant custom integration for the **Haylou Smart Watch 2 (LS02)**.

## Features

- **Device Discovery**: Automatically discovers Haylou Smart Watch 2 devices via Bluetooth
- **Multi-Device Support**: Add multiple watches with custom names
- **Device Tracker**: Track watch connection state (home/away)
- **Heart Rate Sensor**: Receives HBM (heart beat monitor) statistics from the watch
- **Watch Notifications**: Send text messages and alerts to your watch
- **Battery Monitoring**: Track watch battery level
- **Weather Support**: Select any weather entity to be weather source for the watch. Live updates!
- **Steps Count**: Show the steps counted by watch as HA entity
- **User Settings**: Change user-info like age, sex and weight from Home Assistant
- **Watch Settings**: Change settings like "Wrist Mode" directly from Home Assistant

## Installation

### Via HACS (Recommended)

1. Go to **HACS** → **Custom repositories**
2. Add the repository URL: `https://github.com/szupi/haylou_ls02_ha`
3. Select **Integration** as the category
4. Click **Install**
5. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy the `haylou_ls02` folder to `<config>/custom_components/`
3. Restart Home Assistant

## Configuration

### Adding a Haylou Watch

1. Go to **Settings** → **Devices & Services** → **Create Automation**
2. Click **Create Integration** and search for **Haylou LS02**
3. Choose discovery method:
   - **Scan for Haylou Watch**: Automatically finds devices
   - **Enter device address manually**: Use if device is not found
4. Give your watch a friendly name, select weather source and other settings.
5. Confirm the setup

### Multiple Devices

You can add multiple watches. Each will appear as a separate device in Home Assistant with its own entities.

## Available Entities

### Device Tracker
- **`device_tracker.haylou_ls02_<address>`**: Shows "Home" when the watch is detected in the BLE scan, "Away" when not.

### Sensor
- **`sensor.haylou_ls02_heartrate_<address>`**: Displays the latest heart rate measurement in BPM
  - Attributes include: `bpm_current`, `bpm_min`, `bpm_avg`, `bpm_max`, `timestamp`, `battery`

## Services

### send_message

Send a text message to the watch display.

```yaml
service: haylou_ls02.send_message
data:
  message: "Hello from Home Assistant!"
  message_type: "generic"  # or: phone_call, whatsapp, email, facebook, twitter, etc.
```

**Supported message types:**
- `phone_call`
- `qq`
- `wechat`
- `generic`
- `facebook`
- `twitter`
- `whatsapp`
- `skype`
- `messenger`
- `hangouts`
- `line`
- `linkedin`
- `instagram`
- `viber`
- `kakaotalk`
- `vk`
- `snapchat`
- `googleplus`
- `email`
- `flickr`
- `tumblr`
- `pinterest`
- `youtube`

## How It Works

This integration uses Home Assistant's native Bluetooth stack (no external dependencies) to communicate with the Haylou Smart Watch 2 via BLE (Bluetooth Low Energy).

The watch uses proprietary BLE characteristics to exchange commands and notifications. The integration implements the watch protocol to:

1. Connect via BLE
2. Send commands (messages, requests, etc.)
3. Parse incoming notifications (battery status, heart rate statistics)
4. Update Home Assistant entities with watch data

## Troubleshooting

### Device not discovered
- Ensure your Haylou watch is powered on and in Bluetooth range
- Make sure your Home Assistant host supports Bluetooth
- Check Home Assistant logs for Bluetooth-related errors

### Connection issues
- Bring the watch closer to your Home Assistant device
- Restart Home Assistant
- Unpair and re-pair the watch in your system Bluetooth settings
- Make sure to use the same pin that was used in previous connections. Re-pairing with a new pin requires resetting the device to factory defaults.

## Development

This integration was partially vibe-coded using Cursor AI. The base for this implementation was my C++ implementation of a POC command-line tool, which in turn was based on [this excellent RE work of XorTroll](https://github.com/XorTroll/Haywatch).

## License

See LICENSE file in the repository.

## Support

For issues and feature requests, visit the [GitHub repository](https://github.com/szupi/haylou_ls02_ha).
