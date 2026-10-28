// Root build script. Versions live in gradle/libs.versions.toml (the version catalog),
// pinned to a known-good combo (see android/README.md):
//   AGP 9.1.1 · Kotlin 2.2.10 (built into AGP) · Gradle 9.3.1 · JDK 21 · NDK 27
//   · compileSdk 37, targetSdk 36.
// All plugins declared here, applied per-module. AGP 9 compiles Kotlin itself,
// so the kotlin-android plugin is gone.
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.hilt) apply false
}
