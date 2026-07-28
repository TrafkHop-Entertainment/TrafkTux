plugins {
    kotlin("jvm") version "1.9.0"
    application
}

application {
    mainClass.set("MainKt")
}

dependencies {
    implementation(kotlin("stdlib"))
}
