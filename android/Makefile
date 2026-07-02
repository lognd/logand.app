.PHONY: install test coverage clean

# See README.md's "Building on aarch64 Linux" section: Google only ships
# x86_64 aapt2 binaries for Linux, so an aarch64 host (this dev machine)
# needs AGP pointed at a qemu-wrapped aapt2 instead of the one it would
# otherwise resolve from Maven, or every resource-processing task fails
# with "cannot execute binary file: Exec format error".
#
# Overridable via ANDROID_AAPT2_OVERRIDE (e.g. empty on a real x86_64/
# macOS/Windows dev machine, where none of this applies -- see the
# README). Defaults to this machine's known wrapper path but only passes
# the -P flag at all if that path actually exists, so `make test` stays
# a no-op-different plain `./gradlew test` anywhere else.
ANDROID_AAPT2_OVERRIDE ?= /home/logan/.local/opt/aapt2-wrapper/aapt2

ifneq ($(wildcard $(ANDROID_AAPT2_OVERRIDE)),)
GRADLE_AAPT2_FLAG := -Pandroid.aapt2FromMavenOverride=$(ANDROID_AAPT2_OVERRIDE)
else
GRADLE_AAPT2_FLAG :=
endif

# Resolves/downloads every Gradle dependency (AGP, AndroidX, Kotlin
# stdlib, etc.) ahead of time via a no-op-ish task graph -- same purpose
# as `uv sync`/`npm ci` in the other subprojects' `install` targets: a
# separate, explicit "fetch everything the build needs" step, distinct
# from actually compiling/testing anything. `help` is a real Gradle task
# that touches the whole dependency graph without compiling app code,
# same trick used by CI caches elsewhere to warm a dependency cache.
install:
	./gradlew help $(GRADLE_AAPT2_FLAG)

test:
	./gradlew test $(GRADLE_AAPT2_FLAG)

coverage:
	./gradlew :core:jacocoTestReport :app:jacocoTestReport $(GRADLE_AAPT2_FLAG)

clean:
	./gradlew clean $(GRADLE_AAPT2_FLAG)
