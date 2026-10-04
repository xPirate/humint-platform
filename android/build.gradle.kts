plugins {
    // 8.9 is the first AGP that compiles against Android 16 (API 36), which Google
    // Play requires apps to target from 31 August 2026, and it still runs on the
    // Gradle 8.11.1 the build scripts use.
    id("com.android.application") version "8.9.1" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false
    id("com.google.devtools.ksp") version "2.0.21-1.0.28" apply false
}
