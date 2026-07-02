pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "logand-mobile"

// :core is plain Kotlin/JVM (no Android dependency) so it builds and
// tests with a plain JDK+Gradle toolchain alone -- no Android SDK/
// emulator required to verify the networking/business-logic layer,
// which is most of what actually needs real test coverage. :app is the
// real Android application module (Compose UI, manifest, resources)
// that depends on :core.
include(":core")
include(":app")
