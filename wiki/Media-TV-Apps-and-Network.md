# Media, TV, Apps, and Network

## Music

Music plays installed tracks, detected removable-media tracks, audio CDs, and configured radio stations. Shuffle and album playback are available where metadata permits. projectM is used for fullscreen music visualization; lighter cabinet visuals may be used in embedded views for performance.

Use B/East to return from ordinary music screens. If a visualization owns the screen, use the displayed back control or the standard View + Menu exit chord.

## Movies and DVDs

Movie files can be played from removable media or installed under the internal Movies area. TV shows should be organized by show folder to prevent every episode from cluttering the movie gallery.

Movie DVDs launch in a controller-oriented fullscreen player. A/South selects or pauses, directions navigate menus or seek where supported, LB/RB changes chapter, and B/East exits. Disc-menu behavior varies by DVD authoring.

## Live TV and DVR

The public build includes only public/free sources. Users can add authorized M3U/IPTV sources from TV settings. Private usernames, passwords, tokens, and subscription playlists are never part of the public image.

While viewing a supported channel, RB/R1 toggles recording. Recordings appear in the DVR section. Stream availability and program metadata are controlled by the provider; PulseArc can retry an interrupted stream but cannot guarantee a third-party channel remains online.

## Apps

- **Steam Big Picture:** sign in, access owned games, install, and launch through native Steam/Proton.
- **Epic + GOG (Heroic):** sign in to Epic/GOG and install games under the persistent Heroic library.
- **Xbox Game Pass Cloud** and **GeForce NOW:** dedicated controller-oriented web/native launchers; their normal subscription and regional requirements apply.
- **PlayStation Plus Cloud:** isolated Wine-GE integration for Sony's PC cloud client; compatibility can change when Sony updates it.
- **Web Browser:** kiosk/controller browsing with keyboard and mouse available when needed.
- **Downloads & External Media:** imports supported game archives and portable Windows folders.

PulseArc never includes or exports your store credentials in a public image.

## Network, SSH, and file transfer

The current IP address and development login information are displayed at the bottom of the main screen when networking is ready. Development images provide SSH/SFTP for diagnostics and transfers. Change any default/generated password before exposing the machine beyond a trusted home network.

Typical SFTP settings are:

```text
Protocol: SFTP
Host: the IP shown by PulseArc
Port: 22
User: gamer
Password: the password shown/configured on the console
```

Use SFTP rather than plain FTP when possible. Do not expose SSH directly to the public Internet. Themes, covers, music, and authorized media can be copied into their documented user folders; system directories should remain read-only to normal users.

## Bluetooth and Wi-Fi

Use **Extras > Bluetooth** to pair controllers and **Extras > Wi-Fi** to join a wireless network. Wired Ethernet is preferred for large downloads and cloud gaming. Some PCs have Wi-Fi without Bluetooth; pairing requires an actual supported Bluetooth adapter.
