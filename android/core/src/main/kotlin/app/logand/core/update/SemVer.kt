package app.logand.core.update

// Plain major.minor.patch comparison -- deliberately ignores any
// pre-release/build-metadata suffix (e.g. "-beta.1", "+build5") rather
// than implementing full semver 2.0 precedence rules, since every tag
// this repo actually cuts (see .github/workflows/release-android.yml's
// `v*` trigger) is a bare "vX.Y.Z". Comparing components as parsed
// Ints (not the raw strings) is what makes "v1.10.0" correctly sort
// above "v1.9.0" -- a naive string compare would get this backwards.
data class SemVer(val major: Int, val minor: Int, val patch: Int) : Comparable<SemVer> {
    override fun compareTo(other: SemVer): Int =
        compareValuesBy(this, other, SemVer::major, SemVer::minor, SemVer::patch)

    override fun toString(): String = "$major.$minor.$patch"
}

// Accepts an optional leading "v" (GitHub release tags here are always
// "vX.Y.Z", see release-android.yml's tag trigger) and an optional
// trailing pre-release/build suffix, which is parsed and then ignored
// (see SemVer's own doc comment). Returns null for anything that isn't
// at least major.minor.patch -- callers must treat that as "can't
// safely compare, skip this update" rather than guessing.
private val SEMVER_PATTERN = Regex("""^v?(\d+)\.(\d+)\.(\d+)""")

fun parseSemVer(tag: String): SemVer? {
    val match = SEMVER_PATTERN.find(tag.trim()) ?: return null
    val (majorText, minorText, patchText) = match.destructured
    val major = majorText.toIntOrNull() ?: return null
    val minor = minorText.toIntOrNull() ?: return null
    val patch = patchText.toIntOrNull() ?: return null
    return SemVer(major, minor, patch)
}
