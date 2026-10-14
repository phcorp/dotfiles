# Shell and prompt measurements

The default runtime-manager activation and three project-context prompt sections remain unchanged. A single-process context renderer was tested and rejected: it did not produce a meaningful reduction in median prompt latency. The faster native-only reference does not preserve ancestor-project detection or project-only cloud visibility, so it is not a replacement.

## Reproduce

```sh
python3 scripts/benchmark-shell.py --samples 20 --warmups 3
python3 scripts/benchmark-shell.py --only startup --samples 20 --warmups 3
python3 scripts/benchmark-shell.py --only prompts --samples 20 --warmups 3
```

The harness requires at least 15 measured samples and one warmup. It reports wall-clock median and nearest-rank p95 in milliseconds, plus failure counts. Every case uses its own disposable HOME and XDG directories. No private shell startup files are sourced, software is not installed, and command/prompt output is discarded.

NVM code and aliases are staged; installed Node executables are read only. RVM scripts and manager definitions are staged without private user configuration, runtime defaults, project hooks, or the system rvmrc. RVM measurements therefore cover core initialization rather than a complete personal Ruby environment. Optional manager cases are omitted when the corresponding manager is absent.

Measured on 2026-10-14. The host used Darwin arm64, Bash 3.2.57, Zsh 5.9, NVM 0.39.5, RVM 1.29.12-next, Python 3.13.7, and Starship 1.26.0. Measurements ran under the normal host workload, without CPU isolation. Startup initializes the prompt integration but does not render a prompt; rendering is measured separately.

## Startup

Each row uses 20 measured samples after three warmups. Initial measurements were repeated with the final shipping harness and checks that the expected manager functions had initialized; all checks passed. Host-load variation was substantial, especially for Bash with both managers. One intervening loaded repeat measured Bash with both managers at 2076.21 / 2678.14 ms. These values are observations, not guaranteed terminal-open times.

| Shell | Fixture | Initial median / p95 | Final repeat median / p95 |
|---|---|---:|---:|
| Bash | Empty | 5.63 / 6.10 | 10.46 / 12.61 |
| Bash | Managed, no managers | 233.24 / 236.60 | 232.61 / 605.21 |
| Bash | NVM | 491.33 / 507.27 | 503.75 / 553.26 |
| Bash | RVM core | 313.94 / 343.38 | 384.69 / 448.50 |
| Bash | Both | 586.76 / 661.92 | 606.12 / 612.06 |
| Zsh | Empty | 10.18 / 10.96 | 10.90 / 11.29 |
| Zsh | Managed, no managers | 233.78 / 241.69 | 284.87 / 332.34 |
| Zsh | NVM | 1191.14 / 1249.04 | 1400.35 / 1540.26 |
| Zsh | RVM core | 342.51 / 349.99 | 395.79 / 549.54 |
| Zsh | Both | 1252.53 / 1361.58 | 1408.50 / 2080.15 |

The final shipping harness staged NVM `--no-use` reference measured Bash 234.99 / 341.17 ms and Zsh 293.35 / 342.95 ms, with 20 samples, three warmups, and successful function checks. Skipping activation changes the initially selected runtime. It was therefore not chosen as the default; eager NVM/RVM behavior is preserved. The shipping harness includes this explicitly labeled behavior-changing reference.

## Prompt rendering

Fixtures include a plain folder and directories three levels below synthetic Node and AWS project roots. AWS uses a synthetic region without credentials. The native reference enables builtin modules and removes custom context sections; it does not detect the same ancestor context and is only a timing reference.

| Fixture | Current median / p95 | Native reference median / p95 |
|---|---:|---:|
| Plain | 75.35 / 77.91 | 75.09 / 77.82 |
| Nested Node | 129.58 / 132.63 | 75.53 / 78.04 |
| Nested AWS | 130.93 / 133.31 | 75.61 / 77.58 |

All rows used 20 samples and three warmups, with zero command failures. An earlier pass measured plain 75.96 / 124.16 ms, Node 129.10 / 132.80 ms, and AWS 132.82 / 300.57 ms for the current layout. In particular, plain-folder and tail latency varied under host load.

## Rejected single-process diagnostic

The unmerged prototype shared one ancestor traversal, retained the same nearest matching roots, HOME/Git boundaries and read limits, then concatenated native Node/Lua/AWS rendering in the original order. Output equality, styling, native failure isolation, and the individual-module interface were checked before timing it.

| Fixture | Three processes median / p95 | Prototype median / p95 |
|---|---:|---:|
| Plain | 76.35 / 131.17 | 75.89 / 125.10 |
| Nested Node | 128.12 / 178.41 | 126.93 / 130.52 |
| Nested AWS | 128.82 / 130.50 | 128.08 / 131.67 |

These paired measurements used 20 samples and three warmups, with zero failures. Median reductions were less than 1.2 ms. A controlled sleep diagnostic confirmed that Starship runs the original custom sections concurrently; reducing their number did not remove the main critical-path cost. The approximately 55 ms difference from the native reference was not evidence of achievable savings from consolidation.

The prototype and its extra tests were removed. Its diagnostic numbers are retained here for transparency, but that discarded prototype is not reproducible from the shipping harness. The current implementation and native reference remain reproducible with the commands above. Further optimization needs behavior-equivalent measurements before changing runtime activation or project detection.
