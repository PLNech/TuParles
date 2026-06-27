pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
        maven(url = "https://chaquo.com/maven") // Chaquopy plugin (Rung 1+)
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven(url = "https://chaquo.com/maven")
    }
}

rootProject.name = "TuParles"
include(":app")
include(":whisper")
