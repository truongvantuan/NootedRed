# League of Legends Metal verification

27 October 2026. Installed game version: 16.21.8298620.

Riot's current Mac requirements specify Metal-capable graphics. Its transition
notice explains that the client automatically selects Metal as OpenGL support
is retired; an old beta configuration edit is not evidence of current use.

Sources:
- [Riot system requirements](https://support.riotgames.com/en-us/league-of-legends/performance/minimum-and-recommended-system-requirements-league-of-legends)
- [Riot OpenGL-to-Metal transition](https://www.leagueoflegends.com/en-gb/news/game-updates/patch-25-s1-2-notes/)

## Verified locally

The Renoir 0x1636 GPU reports Metal 3 and 1.5 GB VRAM. Earlier bounded tests on
the same NootedRed RELEASE build passed Metal opaque/alpha/dual-source rendering
and 64-element compute readback. This establishes working tested driver paths,
not compatibility with every shader/workload used by the game.

The actual game executable links Metal.framework, QuartzCore and OpenGL.
Linking frameworks establishes availability, not which backend the engine
selects at runtime. game.cfg had no MetalBetaTest or explicit renderer key;
no configuration or game binary was changed by this verification.

## Actual game renderer remains pending

The passive capture observed only LeagueClient/LeagueClientUx and their helpers,
not the Game/LeagueofLegends executable. No r3d game-engine log was created in
the inspected installation's Logs directory. The app inventory also showed the
lobby client running and the game engine not running. The lobby screenshot was
blank/dark; screenshots alone can be unreliable for accelerated content, so
this is not being treated as proof of a failed game renderer.

The user reported the Practice Tool map was loaded. Because this conflicts with
the observed process/log evidence, clarification was requested rather than
claiming success. A lobby map card, champion selection, or a linked Metal
framework does not establish an active Metal match renderer.

Next: load a private Practice Tool session until a champion can be controlled
on the 3D map, then inspect the game renderer initialization log and AMD GPU
clients belonging to that game PID. Check for GPU resets and rendering faults
while moving the camera/casting abilities; do not equate an error-free idle
capture with a successful game-rendering test. Keep normal game settings until
the actual selected backend is identified.

The observer reads process names, game graphics logs and IORegistry only.
It does not launch a match, attach a debugger, inject a library, alter the game,
or change security settings. The completed three-minute capture had no observed
kernel GPU reset or hang, but did not observe the game engine.

Evidence: `build/lol-metal-verification-20261027/VERIFICATION.json`, linked
framework/capability records, and `capture-20261027-194503/SUMMARY.json`.

## Runtime result: verified Metal

At 19:51, the actual LeagueofLegends game process (PID 3405) was observed.
Its fresh 19:50:14 r3d log explicitly records:

```text
Metal Device GPU: AMD Radeon RX Renoir Graphics
Metal Device Approx VRAM: 1536mb
Using X3D Platform: Metal
Metal Support: Metal 3
```

This supersedes the earlier pending result. The actual game engine selected
Metal; this is not an inference from the lobby or framework imports. No game
configuration change was required or made. Performance, longer-term stability
and completion of an in-match Vanguard check are separate observations.
