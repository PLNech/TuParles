// The dictaphone app: single-activity Compose, Hilt DI, Room storage.
// Phase A (record / save / share). Deliberately does NOT depend on :whisper —
// Phase B wires the native engine behind TranscriptionEngine. No INTERNET.
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
    alias(libs.plugins.hilt)
}

// Release signing credentials from the environment (see .env / .env.example) so
// nothing secret is committed. The store password doubles as the key password.
val uploadKeystorePath = providers.environmentVariable("TUPARLES_UPLOAD_KEYSTORE").orNull
val uploadKeyAlias = providers.environmentVariable("TUPARLES_UPLOAD_KEY_ALIAS").orNull
val uploadKeystorePass = providers.environmentVariable("TUPARLES_UPLOAD_KEYSTORE_PASS").orNull
val hasUploadSigning = uploadKeystorePath != null && uploadKeyAlias != null && uploadKeystorePass != null

android {
    namespace = "pl.nech.tuparles"
    compileSdk = 36

    defaultConfig {
        applicationId = "pl.nech.tuparles"
        minSdk = 26 // no more Chaquopy floor; covers ~95% of devices
        targetSdk = 36
        versionCode = 4
        versionName = "1.0.0-internal1" // First Play internal-testing upload
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        create("release") {
            if (hasUploadSigning) {
                storeFile = file(uploadKeystorePath!!)
                storePassword = uploadKeystorePass
                keyAlias = uploadKeyAlias
                keyPassword = uploadKeystorePass
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (hasUploadSigning) signingConfigs.getByName("release") else null
        }
    }

    buildFeatures {
        compose = true
    }

    // The whisper GGML model ships as an UNCOMPRESSED asset (POC lesson): the JNI
    // loader mmaps/streams it straight from the APK instead of inflating ~142MB into
    // heap. The model itself is fetched by scripts/fetch-android-model.sh and gitignored.
    androidResources {
        noCompress += "bin"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    testOptions {
        // Let android.jar stubs (e.g. android.util.Log) return defaults instead of
        // throwing "not mocked" so pure-logic JVM tests can exercise code that logs.
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    // Phase B: on-device STT engine (vendored whisper.cpp + JNI). Builds libwhisper.so
    // for arm64 via the NDK; the app degrades to Phase A if no model asset is present.
    implementation(project(":whisper"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.google.material) // XML DayNight theme host for the Compose activity

    // Compose
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.extended)
    debugImplementation(libs.androidx.compose.ui.tooling)

    // DI
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.androidx.hilt.navigation.compose)

    // Room
    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)

    // Tests (pure JVM)
    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)

    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.test.runner)
}

// Fail fast on a release assemble/bundle/sign task when signing env vars are
// missing, rather than emitting an unsigned bundle Play rejects. Debug builds
// and non-build tasks are unaffected.
gradle.taskGraph.whenReady {
    val wantsSignedRelease = allTasks.any { t ->
        val n = t.name.lowercase()
        n.contains("bundlerelease") || n.contains("assemblerelease") || n.contains("signrelease")
    }
    if (wantsSignedRelease && !hasUploadSigning) {
        throw GradleException(
            "Release signing requires env vars TUPARLES_UPLOAD_KEYSTORE, " +
            "TUPARLES_UPLOAD_KEY_ALIAS, TUPARLES_UPLOAD_KEYSTORE_PASS. See .env.example.",
        )
    }
}
