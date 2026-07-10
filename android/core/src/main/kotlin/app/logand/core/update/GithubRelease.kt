package app.logand.core.update

import kotlinx.serialization.Serializable

// Field names match GitHub's real Releases API response verbatim
// (docs.github.com/en/rest/releases/releases#get-the-latest-release),
// not renamed to this codebase's usual camelCase -- ignoreUnknownKeys
// (see UpdateChecker's Json instance) means every other field GitHub
// returns is simply dropped, so only what's actually used is modeled.
@Serializable
data class GithubReleaseAsset(
    val name: String,
    val browser_download_url: String,
)

@Serializable
data class GithubRelease(
    val tag_name: String,
    val assets: List<GithubReleaseAsset> = emptyList(),
)

// What a caller (UpdateViewModel in :app) actually needs to offer an
// update -- the release tag (for display) and the direct APK download
// URL, already resolved out of GithubRelease.assets.
data class UpdateInfo(val version: String, val downloadUrl: String)
