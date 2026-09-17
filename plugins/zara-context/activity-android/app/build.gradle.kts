plugins { id("com.android.application") }

android {
    namespace = "ai.zara.activity"
    compileSdk = 36

    defaultConfig {
        applicationId = "ai.zara.activity"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0-alpha.1"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
