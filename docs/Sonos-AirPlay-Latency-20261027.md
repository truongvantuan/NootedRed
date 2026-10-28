# Sonos Five AirPlay response delay — 27 October 2026

The user reported delayed start/response when selecting Sonos Five as macOS
system AirPlay output. The active AirPlay engine logged a 2000 ms audio latency;
a read-only CoreAudio stream probe independently reported 88200 latency frames
at 44100 Hz (2000 ms). Device-level latency alone reports zero for this AirPlay
device and must not be mistaken for zero actual stream latency.

The speaker advertises both AirPlay and RAOP over Bonjour. A short 20-packet
ping test had zero loss and 1.742 ms average round-trip latency (range 1.324–3.623
ms). This and the explicit engine buffer explain the response delay better than
attributing it to a Wi-Fi driver fault. This sample does not prove the network
never has jitter or measure acoustic end-to-end delay.

## Applied and verified improvement

Saved original audioLatencyMs key presence/values from root and system
com.apple.airplay preference domains. Both keys were absent. Wrote 1000 ms to
those two domains and restarted only AirPlayXPCHelper. The user re-selected
Sonos Five and resumed playback. No coreaudiod restart, preference-domain reset,
third-party application/helper installation, launch daemon, EFI change, kext
change or driver binary patch was performed.

The new AirPlay engine explicitly logged the 1000 ms override. CoreAudio now
reports 44100 stream-latency frames at 44100 Hz (1000 ms), with AirPlay still the
default output. The user confirmed shorter response delay and smooth audio.
This halves the configured stream buffer; it does not establish exact audible
latency or its percentage improvement. Initial listening passed; long-duration
playback under network contention has not been measured.

This is an undocumented preference, studied by the Preroll project, not a
supported Sonos or Apple latency slider. Its effect was verified locally on
macOS 15.8.1 x86_64 rather than inferred from Preroll's newer-macOS tests. The
preference affects system AirPlay output generally, not only Sonos Five. Lower
buffering can reduce tolerance for network jitter; 1000 ms was retained because
the user reported smooth playback. No 350 ms or 250 ms experiment was applied.

## Rollback

```sh
sudo python3 /Users/tvtuan/Github/NootedRed/build/sonos-latency-20261027/set-latency.py --restore
```

This restores only the two saved keys (deletes them for this recorded baseline)
and restarts AirPlayXPCHelper. Re-select the speaker afterward. The normal
engine should return to its original reported buffer; verify with the probe
and logs. The preferences are preserved across reboots unless changed or reset
by macOS; future updates can change undocumented behavior.

Evidence: build/sonos-latency-20261027/; SUMMARY.json records measured and
user-confirmed observations. No audio was recorded from the microphone.

Sources:
- Sonos documents delay/interruptions with macOS system AirPlay audio: https://support.sonos.com/en-ca/article/stream-airplay-audio-to-sonos
- Apple documents possible 2-second AirPlay output latency: https://developer.apple.com/documentation/avfaudio/avaudiosession/outputlatency
- Undocumented preference mechanism and helper restart: https://github.com/ksha23/preroll/blob/main/helper/preroll-helper.sh

## Further tuning — final setting 500 ms

The user requested a further reduction. A staged 500 ms test negotiated 22050
stream frames at 44100 Hz; the user confirmed smooth playback and requested
a 350 ms trial. The AirPlay engine accepted 350 ms, but the user reported
playback problems and requested rollback to 500 ms. The sender was restarted
and 500 ms restored. CoreAudio again reports 22050 frames / 500 ms as the
default AirPlay output, and the user confirmed smooth playback returned.

Retain **500 ms**, the lowest tested setting with smooth user-confirmed
playback. The nominal buffer is 75% below the original 2000 ms, without claiming
that acoustic latency fell by that percentage. No 250 ms or 400 ms trial was
performed. The initial 1000 ms result above is historical and superseded by
this final 500 ms setting. All changes and previous key values are recorded
in preference-change-history.jsonl; preference-backup.json still preserves the
original absent-key state. No startup helper, keepalive, EFI or kext change
was introduced. Long-duration testing under network load remains unperformed.

The set-latency.py helper now accepts only the controlled 350/500/1000 ms
steps and --restore. Run with sudo and re-select the speaker after each helper
restart. To return to the prior conservative setting use argument 1000;
--restore instead restores the original macOS defaults from the baseline.

For music, Sonos supports direct control from services such as Spotify. Using
that route avoids sending the Mac's system-audio stream, but does not promise
zero playback-control delay or apply to arbitrary Mac app audio. Ethernet is
an optional future network-comparison test to reduce wireless variability;
the present good ping results provide no reason for disruptive router/EFI
changes, nor prove that Ethernet would make 350 ms stable.

Additional sources:
- https://support.sonos.com/en-us/article/stream-audio-to-sonos-from-another-app
- https://support.sonos.com/en/article/recommended-settings-for-using-sonos-with-ethernet-networks
- https://github.com/ksha23/preroll/blob/main/NOTES.md
