plugins { id("com.android.application") }
android {
    namespace = "ai.zara.companion"
    compileSdk = 36
    defaultConfig {
        applicationId = "ai.zara.companion"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0-alpha.1"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/rendererAssets"))
}
dependencies { implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2") }
val stageRenderer by tasks.registering(Exec::class) {
    workingDir(rootProject.projectDir)
    commandLine("python3", "stage_assets.py", layout.buildDirectory.dir("generated/rendererAssets").get().asFile)
    inputs.dir(rootProject.file("web"))
    inputs.file(rootProject.file("../renderer/package-lock.json"))
    inputs.file(rootProject.file("stage_assets.py"))
    outputs.dir(layout.buildDirectory.dir("generated/rendererAssets"))
}
tasks.named("preBuild") { dependsOn(stageRenderer) }
