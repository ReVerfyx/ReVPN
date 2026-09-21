package com.reverfyx.revpn.auth

import android.app.Activity
import android.content.MutableContextWrapper
import android.util.Base64
import androidx.credentials.ClearCredentialStateRequest
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialException
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import java.security.SecureRandom

object GoogleAuthManager {

    suspend fun signIn(activity: Activity): Result<GoogleAccount> = runCatching {
        val clientId = AuthStore.googleWebClientId(activity)
        require(clientId.isNotBlank()) { "Google вход не настроен" }

        val manager = CredentialManager.create(activity)
        val context = MutableContextWrapper(activity)

        val result = try {
            val option = GetGoogleIdOption.Builder()
                .setFilterByAuthorizedAccounts(false)
                .setServerClientId(clientId)
                .setAutoSelectEnabled(false)
                .setNonce(generateNonce())
                .build()

            manager.getCredential(
                context = context,
                request = GetCredentialRequest.Builder()
                    .addCredentialOption(option)
                    .build()
            )
        } catch (first: GetCredentialException) {
            try {
                val buttonOption = GetSignInWithGoogleOption.Builder(
                    serverClientId = clientId
                )
                    .setNonce(generateNonce())
                    .build()

                manager.getCredential(
                    context = context,
                    request = GetCredentialRequest.Builder()
                        .addCredentialOption(buttonOption)
                        .build()
                )
            } catch (second: GetCredentialException) {
                val details = second.message.orEmpty()
                if (details.contains("reauth", ignoreCase = true) || details.contains("[16]")) {
                    error("Google просит повторно подтвердить аккаунт. Открой настройки Google-аккаунта на телефоне, подтверди вход и попробуй ещё раз.")
                }
                throw second
            }
        }

        val custom = result.credential as? CustomCredential
            ?: error("Google не вернул данные аккаунта")

        require(custom.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
            "Google вернул неподдерживаемый тип входа"
        }

        val credential = GoogleIdTokenCredential.createFrom(custom.data)
        val account = GoogleAccount(
            uniqueId = credential.id,
            email = credential.id,
            displayName = credential.displayName.orEmpty(),
            photoUrl = credential.profilePictureUri?.toString()
        )
        AuthStore.saveAccount(activity, account)
        account
    }

    suspend fun signOut(activity: Activity): Result<Unit> = runCatching {
        CredentialManager.create(activity)
            .clearCredentialState(ClearCredentialStateRequest())
        AuthStore.clearAccount(activity)
    }

    private fun generateNonce(): String {
        val bytes = ByteArray(32)
        SecureRandom().nextBytes(bytes)
        return Base64.encodeToString(
            bytes,
            Base64.NO_WRAP or Base64.URL_SAFE or Base64.NO_PADDING
        )
    }
}
