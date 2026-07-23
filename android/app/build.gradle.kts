// The dictaphone app: single-activity Compose, Hilt DI, Room storage. Records offline;
// on-device STT via the vendored :whisper engine, with the speech model fetched at
// runtime (lean APK, #13) rather than bundled. The one network use is inbound model
// download from huggingface.co — no user data ever leaves the device.
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
        versionCode = 6
        versionName = "1.0.0" // First public 1.0: lean APK + model download, rolling transcript, dotprod tier
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

    androidResources {
        // GGML weights stay UNCOMPRESSED (POC lesson): the JNI loader streams them
        // straight instead of inflating hundreds of MB into heap. Applies to a
        // downloaded model on disk and to any dev-bundled asset alike.
        noCompress += "bin"
        // Lean APK (#13): never package the dev model directory. A clean checkout has
        // nothing under assets/models (it is gitignored), and this guarantees the
        // shipped app stays lean even on a dev box that ran fetch-android-model.sh —
        // the model is downloaded at first run instead. A dev who genuinely wants a
        // bundled build (offline demo) drops this one line. The engine keeps the
        // asset-load path, so such a build still works.
        ignoreAssetsPatterns += "models"
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

    lint {
        // TOOLING-CRASH WORKAROUND (not a real-issue suppression). Under AGP 8.9.0 the
        // Compose-runtime `MutableCollectionMutableStateDetector` throws a
        // NoClassDefFoundError mid-analysis (its Kt facade fails to load), aborting the
        // whole lint run with "this is a bug in lint or one of the libraries it depends
        // on". Lint's own error message recommends disabling this one check; doing so
        // lets lint complete and report genuine findings. Revisit when AGP/Compose lint
        // are bumped — this is a crash, not a finding we are hiding.
        disable += "MutableCollectionMutableState"
    }
}

// Room exports its generated schema JSON so migrations can be written against the exact
// DDL Room validates at open time, and the schema history is checked in.
ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
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
