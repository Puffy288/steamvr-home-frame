# Build and implementation notes

The installer and launcher are Python and Bash. The private Vulkan adapter is C++17 with an original GLSL shader. It is process-local and only matches a hash-identified shader and specific four-sample, depth-only pipelines in the supported Home build. Valve code and shader bytes are not included.

The optional alpha-tested depth prepass can cover pixels whose final colour pass leaves some MSAA samples uncovered. The correction restricts the depth shortcut to near-opaque texel interiors, while preserving the original colour and shadow passes. The correction applies only to the matched pipelines in the supported game build.

## Build on ARM64 Linux

Use a developer environment with Python 3.11+, a C++17 compiler, Vulkan headers, OpenSSL development headers, `glslangValidator` and `spirv-val`. Ordinary users do not need these tools. The included binary is for ARM64; do not replace it with an x86 build.

```bash
python3 coverage/build.py
python3 -m unittest discover -s tests -v
g++ -std=c++17 -O2 tests/test_coverage_layer.cpp -lcrypto -o /tmp/home-coverage-test
/tmp/home-coverage-test
python3 build_release.py
FRAME_HOME_INSTALL_TERMINAL=1 bash dist/SteamVR-Home-Frame-Install.run --extract-only
```

`coverage/build.py` compiles only the original shader/adapter and updates their integrity data. `supported-game.json` contains hashes of the supported game files, not their contents. `expected.h` contains only the matched shader's length and SHA-256 digest. The runtime disables the optional prepass when the game or package does not pass its guard.

`build_release.py` uses an explicit file allowlist. The resulting self-contained `.run` embeds the source archive and verifies its SHA-256 before safe extraction. Runtime game downloads still come from Valve. The public source archive intentionally includes our compiled ARM64 adapter and its complete source so the normal installer does not need a compiler.
