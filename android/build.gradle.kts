// Root build script. Versions live in gradle/libs.versions.toml (the version catalog),
// pinned to a known-good combo (see android/README.md):
//   AGP 8.9 · Kotlin 2.0.21 · Gradle 8.11.1 · JDK 21 · NDK 27 · compileSdk 36.
// All plugins declared here, applied per-module.
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.hilt) apply false
}
