// Root build script. Versions pinned to a known-good combo (see android/README.md):
//   Chaquopy 17.0 ↔ AGP 8.9 ↔ Gradle 8.11.1 ↔ Kotlin 2.0.x ↔ JDK 21.
// Chaquopy is declared here but applied only from the app module at Rung 1.
plugins {
    id("com.android.application") version "8.9.0" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("com.chaquo.python") version "17.0.0" apply false
}
