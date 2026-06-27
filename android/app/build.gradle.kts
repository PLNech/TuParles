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

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
}

// The postprocess core is the SAME src/ the desktop daemon and eval harness use —
// no copy, no fork. The lean chain (pipeline → casing/lexicon/punctuation/repeats/
// syntax/syntax_features → config_core) is pure stdlib, so no pip deps are needed;
// the heavy desktop modules (daemon, ui, engine) ship as unused bytecode.
chaquopy {
    defaultConfig {
        version = "3.12"
    }
    sourceSets {
        getByName("main") {
            srcDir("../../src")
        }
    }
}
