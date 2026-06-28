// Rung 0: a minimal app that proves the device loop (build → install → run).
// Chaquopy (Rung 1) and the whisper.cpp JNI engine (Rung 2) layer on from here.
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python") // Rung 1: embed the portable postprocess core
}

android {
    namespace = "pl.nech.tuparles"
    compileSdk = 36

    defaultConfig {
        applicationId = "pl.nech.tuparles"
        minSdk = 24 // Chaquopy 17 floor; covers ~97% of devices
        targetSdk = 36
        versionCode = 1
        versionName = "0.1-spike"

        // Chaquopy ships a per-ABI Python runtime; arm64 = phones, x86_64 = emulator.
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    // BuildConfig.DEBUG / VERSION_NAME drive the flavor-aware telemetry (debug-only
    // INTERNET + domovoy sync vs the INTERNET-free release). AGP 8 needs this opt-in.
    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    // The bundled GGML model must stay uncompressed so whisper can load it from
    // the asset without inflating 140MB into RAM. Fetch it with
    // scripts/fetch-android-model.sh before building (it's gitignored — >100MB).
    androidResources {
        noCompress += "bin"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation(project(":whisper")) // Rung 2: native whisper.cpp engine
    testImplementation("junit:junit:4.13.2") // pure-JVM unit tests (framework-free helpers)
}

// The postprocess core is the SAME source the desktop daemon and eval harness
// use — no copy, no fork. Since the core/desktop namespace split (refactor #10),
// we mount ONLY the portable distribution (packages/tuparles-core/src): the lean
// chain (pipeline → casing/lexicon/punctuation/repeats/syntax/syntax_features →
// config_core) is pure stdlib, and the heavy desktop modules no longer sit on the
// Android Python path at all. getModule("tuparles.pipeline") is unchanged — the
// shared `tuparles` namespace is preserved by the split (PEP 420).
chaquopy {
    defaultConfig {
        version = "3.12"
    }
    sourceSets {
        getByName("main") {
            srcDir("../../packages/tuparles-core/src")
        }
    }
}
