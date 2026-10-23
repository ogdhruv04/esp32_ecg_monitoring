plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// The repo's recordings, used by replay mode and ReplayPipelineTest.
val capturesDir = rootProject.file("../captures")

android {
    namespace = "com.dhruv.ecgmonitor"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.dhruv.ecgmonitor"
        minSdk = 31
        targetSdk = 34
        versionCode = 1
        versionName = "0.1"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
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

    testOptions {
        // Robolectric needs merged resources and assets (replay captures).
        unitTests.isIncludeAndroidResources = true
        unitTests.all {
            // ReplayPipelineTest reads real recordings straight from the repo.
            it.systemProperty("captures.dir", capturesDir.absolutePath)
            // Screenshot tests render on every testDebugUnitTest run, into
            // android_app/screenshots/ (paths are chosen per test).
            it.systemProperty("roborazzi.test.record", "true")
            it.systemProperty("screenshots.dir", rootProject.file("screenshots").absolutePath)
        }
    }
}

// Recordings bundled into debug builds for replay mode, renamed to short
// asset names (`--es replay dual03_ring`). In these runs the ring board (C3)
// was on the chest and the reference (WROOM) on the finger. Chosen to cover
// every state of the app's gate (analysis/sqi_replay_app_gate_dual01-03.txt):
// dual03 both GOOD 100%, dual02 chest FAIR 85.3%, dual01 chest POOR 90.9%.
val replayCaptures = mapOf(
    "dual03_ring.csv" to "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ring.csv",
    "dual03_ref.csv" to "20260929_163314_dual03_both3wire_c3chest_wroomfinger_ref.csv",
    "dual02_ring.csv" to "20260929_155511_dual02_rbias_c3chest_wroomfinger_ring.csv",
    "dual01_ring.csv" to "20260929_153252_dual01_c3chest_wroomfinger_ring.csv",
)

abstract class CopyReplayCaptures : DefaultTask() {
    @get:InputFiles abstract val sources: ConfigurableFileCollection
    @get:Input abstract val names: MapProperty<String, String>
    @get:OutputDirectory abstract val outputDir: DirectoryProperty

    @TaskAction
    fun copy() {
        val dir = outputDir.get().asFile.resolve("replay")
        dir.deleteRecursively()
        dir.mkdirs()
        val byName = sources.files.associateBy { it.name }
        names.get().forEach { (asset, capture) ->
            byName.getValue(capture).copyTo(dir.resolve(asset))
        }
    }
}

val copyReplayCaptures = tasks.register<CopyReplayCaptures>("copyReplayCaptures") {
    sources.from(replayCaptures.values.map { capturesDir.resolve(it) })
    names.set(replayCaptures)
    outputDir.set(layout.buildDirectory.dir("generated/replayAssets"))
}

androidComponents {
    onVariants(selector().withBuildType("debug")) { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(copyReplayCaptures, CopyReplayCaptures::outputDir)
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.13")
    testImplementation("io.github.takahirom.roborazzi:roborazzi:1.26.0")
    testImplementation("io.github.takahirom.roborazzi:roborazzi-compose:1.26.0")
    testImplementation("androidx.compose.ui:ui-test-junit4")
    testImplementation("androidx.test.ext:junit:1.2.1")
    // Hosts createComposeRule()'s activity in debug builds.
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
