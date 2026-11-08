import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}
android {
    namespace = "com.example.cryptobottommonitor"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.example.cryptobottommonitor"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "0.2.0"
        val backendUrl = providers.gradleProperty("BACKEND_BASE_URL")
            .orElse(providers.environmentVariable("BACKEND_BASE_URL"))
            .getOrElse("http://10.0.2.2:8000/")
            .let { if (it.endsWith("/")) it else "$it/" }
        buildConfigField("String", "BASE_URL", "\"$backendUrl\"")
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true; buildConfig = true }
}
kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}
dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.10.0")
    implementation(platform("androidx.compose:compose-bom:2025.02.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-gson:2.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
