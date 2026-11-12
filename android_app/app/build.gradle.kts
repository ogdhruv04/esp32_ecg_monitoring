plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")
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
            // Signed with the debug key so it installs for on-phone checks.
            // A build for anyone else needs its own release key.
            signingConfig = signingConfigs.getByName("debug")
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
    // The only captures of ours longer than a 3-minute Session (test board,
    // 27 Oct 2026; analysis/app_session_reference.txt).
    "tb01.csv" to "20261027_173714_testboard01.csv",
    "tb02.csv" to "20261027_174352_testboard02.csv",
)

// Public-dataset records converted to capture format by make_public_replay.py.
// The directory is gitignored (datasets are never committed, docs/datasets.md)
// and optional: a build without it simply has no public replays.
val publicReplayDir = rootProject.file("replay_public")

abstract class CopyReplayCaptures : DefaultTask() {
    @get:InputFiles abstract val sources: ConfigurableFileCollection
    @get:InputFiles abstract val extra: ConfigurableFileCollection
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
        extra.files.filter { it.isFile && it.name.endsWith(".csv") }.forEach { it.copyTo(dir.resolve(it.name)) }
    }
}

val copyReplayCaptures = tasks.register<CopyReplayCaptures>("copyReplayCaptures") {
    sources.from(replayCaptures.values.map { capturesDir.resolve(it) })
    names.set(replayCaptures)
    extra.from(project.fileTree(publicReplayDir))
    outputDir.set(layout.buildDirectory.dir("generated/replayAssets"))
}

androidComponents {
    onVariants(selector().withBuildType("debug")) { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(copyReplayCaptures, CopyReplayCaptures::outputDir)
    }
}

// Room writes each schema version here; committed, so a later migration has
// the old schema to test against.
ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
    // Kotlin output: the module has no Java, and this JDK has no jlink for javac's system image.
    arg("room.generateKotlin", "true")
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.09.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")
    // Session history (SessionStore.kt).
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")

    testImplementation("junit:junit:4.13.2")
    // Real org.json for plain JVM tests (android.jar's copy is a stub there):
    // AlgorithmsConfigTest reads algorithms/config.json with it.
    testImplementation("org.json:json:20240303")
    testImplementation("org.robolectric:robolectric:4.13")
    testImplementation("io.github.takahirom.roborazzi:roborazzi:1.26.0")
    testImplementation("io.github.takahirom.roborazzi:roborazzi-compose:1.26.0")
    testImplementation("androidx.compose.ui:ui-test-junit4")
    testImplementation("androidx.test.ext:junit:1.2.1")
    // Hosts createComposeRule()'s activity in debug builds.
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
