package com.reverfyx.revpn.auth

import android.content.Context
import com.reverfyx.revpn.BuildConfig

data class GoogleAccount(
    val uniqueId: String,
    val email: String,
    val displayName: String,
    val photoUrl: String?
)

object AuthStore {
    private const val PREFS = "revpn_auth"
    private const val KEY_ID = "google_unique_id"
    private const val KEY_EMAIL = "google_email"
    private const val KEY_NAME = "google_display_name"
    private const val KEY_PHOTO = "google_photo"
    private const val KEY_CLIENT_ID = "google_web_client_id"

    fun account(context: Context): GoogleAccount? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val id = prefs.getString(KEY_ID, null)?.takeIf { it.isNotBlank() } ?: return null
        return GoogleAccount(
            uniqueId = id,
            email = prefs.getString(KEY_EMAIL, "").orEmpty(),
            displayName = prefs.getString(KEY_NAME, "").orEmpty(),
            photoUrl = prefs.getString(KEY_PHOTO, null)
        )
    }

    fun isSignedIn(context: Context): Boolean = account(context) != null

    fun saveAccount(context: Context, account: GoogleAccount) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY_ID, account.uniqueId)
            .putString(KEY_EMAIL, account.email)
            .putString(KEY_NAME, account.displayName)
            .putString(KEY_PHOTO, account.photoUrl)
            .apply()
    }

    fun clearAccount(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .remove(KEY_ID)
            .remove(KEY_EMAIL)
            .remove(KEY_NAME)
            .remove(KEY_PHOTO)
            .apply()
    }

    fun googleWebClientId(context: Context): String {
        val local = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_CLIENT_ID, "")
            .orEmpty()
            .trim()
        return local.ifBlank { BuildConfig.GOOGLE_WEB_CLIENT_ID.trim() }
    }

    fun saveGoogleWebClientId(context: Context, value: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY_CLIENT_ID, value.trim())
            .apply()
    }
}
