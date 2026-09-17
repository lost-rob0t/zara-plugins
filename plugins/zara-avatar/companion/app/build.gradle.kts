plugins { id("com.android.application") }
android {
    namespace = "ai.zara.companion"
    compileSdk = 36
    defaultConfig {
        applicationId = "ai.zara.companion"
        minSdk = 29
        targetSdk = 36
        versionCode = 2
        versionName = "0.1.0-alpha.2"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    // AGP 9 rejects Provider values here; preBuild below owns the producer dependency.
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/rendererAssets").get().asFile)
    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/fixtureAssets").get().asFile)
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
val stageTestAvatar by tasks.registering(Exec::class) {
    workingDir(rootProject.projectDir)
    commandLine("python3", "tools/make_test_vrm.py",
        layout.buildDirectory.file("generated/fixtureAssets/default-avatar.vrm").get().asFile)
    inputs.file(rootProject.file("tools/make_test_vrm.py"))
    outputs.dir(layout.buildDirectory.dir("generated/fixtureAssets"))
}
tasks.named("preBuild") { dependsOn(stageRenderer, stageTestAvatar) }
