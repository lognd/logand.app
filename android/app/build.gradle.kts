plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    jacoco
}

android {
    namespace = "app.logand.mobile"
    compileSdk = 34

    defaultConfig {
        applicationId = "app.logand.mobile"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        versionName = "1.0.1"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
        debug {
            enableUnitTestCoverage = true
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    composeOptions {
        // Last Compose compiler release compatible with Kotlin 1.9.24 (the
        // Kotlin version this whole project pins, chosen so :core -- pure
        // Kotlin/JVM, no Android dependency -- and :app share one Kotlin
        // version rather than needing two).
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }

    testOptions {
        unitTests {
            isIncludeAndroidResources = true
            isReturnDefaultValues = true
        }
    }
}

dependencies {
    implementation(project(":core"))

    implementation(platform("androidx.compose:compose-bom:2024.06.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.2")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.2")
    implementation("androidx.navigation:navigation-compose:2.7.7")
    implementation("androidx.core:core-ktx:1.13.1")
    // XML-side Material3 theme (Theme.Material3.DayNight.NoActionBar in
    // res/values/themes.xml) -- distinct from the Compose Material3
    // library above; needed for the pre-Compose window theme only (see
    // themes.xml's own doc comment).
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.datastore:datastore-preferences:1.1.1")

    testImplementation("org.jetbrains.kotlin:kotlin-test-junit5")
    testRuntimeOnly("org.junit.jupiter:junit-jupiter-engine:5.10.2")
    // Bridges Robolectric's JUnit4 (@RunWith(RobolectricTestRunner::class))
    // tests into the JUnit5 Platform so `useJUnitPlatform()` can run both
    // styles of test in one `test` task.
    testRuntimeOnly("org.junit.vintage:junit-vintage-engine:5.10.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("org.robolectric:robolectric:4.13")
    testImplementation("androidx.test:core-ktx:1.6.1")
    // Compose UI testing under Robolectric (NOT only androidTest scope --
    // no emulator is available on this host, see README's aarch64
    // section, so screen-level tests run as Robolectric unit tests).
    // ui-test-manifest contributes the empty ComponentActivity
    // createComposeRule() launches; isIncludeAndroidResources above is
    // what lets Robolectric see it. Debug-variant ONLY (and the matching
    // tests live in src/testDebug/): ui-test-manifest's activity never
    // reaches the RELEASE test manifest, so under testReleaseUnitTest
    // createComposeRule() dies with "Unable to resolve activity" --
    // scoping both the deps and the tests to debug keeps `gradlew test`
    // (which runs BOTH variants) green instead of double-running
    // UI-shaped tests that can only ever work in one of them.
    testDebugImplementation(platform("androidx.compose:compose-bom:2024.06.00"))
    testDebugImplementation("androidx.compose.ui:ui-test-junit4")
    testDebugImplementation("androidx.compose.ui:ui-test-manifest")
    // Robolectric's Android sandbox loads conscrypt (for TLS) at startup
    // regardless of whether a given test touches networking --
    // conscrypt-openjdk-uber only shipped a linux-aarch64 native build
    // starting with 2.6-alpha5 (nothing in any stable 2.x release), which
    // this host (aarch64 Linux) needs. See android/README.md's aarch64
    // setup notes.
    testImplementation("org.conscrypt:conscrypt-openjdk-uber:2.6-alpha5")

    androidTestImplementation(platform("androidx.compose:compose-bom:2024.06.00"))
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}

tasks.register<JacocoReport>("jacocoTestReport") {
    dependsOn("testDebugUnitTest")
    reports {
        xml.required.set(true)
        html.required.set(true)
    }
    val fileFilter = listOf(
        "**/R.class", "**/R\$*.class", "**/BuildConfig.*", "**/Manifest*.*",
        "**/*Test*.*", "android/**/*.*",
        // Compose-generated synthetic classes -- @Composable functions
        // compile to classes JaCoCo can't meaningfully attribute line
        // coverage to (Compose's own compiler-generated slot-table
        // plumbing), same reasoning the backend's own coverage config
        // excludes migrations/testing infra it can't usefully measure.
        "**/ComposableSingletons\$*.*",
    )
    val debugTree = fileTree("${project.layout.buildDirectory.get()}/tmp/kotlin-classes/debug") {
        exclude(fileFilter)
    }
    classDirectories.setFrom(files(debugTree))
    sourceDirectories.setFrom(files("src/main/kotlin"))
    executionData.setFrom(
        fileTree(project.layout.buildDirectory.get()) {
            include("outputs/unit_test_code_coverage/debugUnitTest/testDebugUnitTest.exec")
        }
    )
}

tasks.withType<Test> {
    useJUnitPlatform()
    // robolectric.offline -- ONLY on aarch64 Linux with the local jar
    // cache actually populated (this dev host; see android/README.md's
    // aarch64 setup steps). Robolectric's remote-artifact fetcher
    // initializes conscrypt (for TLS) purely to CHECK for a newer
    // android-all jar even when one is already cached locally, and
    // conscrypt-openjdk-uber has never published a linux-aarch64 native
    // build, so that initialization always throws UnsatisfiedLinkError
    // on THIS architecture regardless of what the test itself does.
    // Forcing offline mode (using only the already-resolved local Maven
    // cache) sidesteps the network/TLS path entirely -- but unlike
    // aarch64, x86_64 (every CI runner: android-ci.yml/
    // release-android.yml both run on ubuntu-latest, which is x86_64)
    // has no such conscrypt gap, so forcing offline mode there just
    // makes Robolectric's LocalDependencyResolver fail outright looking
    // for a flat-file jar cache directory that was never populated
    // (IllegalArgumentException) instead of resolving normally online.
    val robolectricDepsDir = File(
        System.getProperty("user.home"),
        ".local/opt/robolectric-deps",
    )
    val isAarch64Linux = System.getProperty("os.arch") in setOf("aarch64", "arm64") &&
        System.getProperty("os.name").contains("Linux", ignoreCase = true)
    if (isAarch64Linux && robolectricDepsDir.isDirectory) {
        systemProperty("robolectric.offline", "true")
        // Flat directory (Robolectric's LocalDependencyResolver expects
        // the jar directly at <dir>/<artifact>.jar, not a real Maven
        // layout).
        systemProperty("robolectric.dependency.dir", robolectricDepsDir.absolutePath)
    }
}
