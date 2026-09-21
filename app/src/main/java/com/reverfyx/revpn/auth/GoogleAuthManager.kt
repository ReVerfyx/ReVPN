package com.reverfyx.revpn.auth

import android.app.Activity
import android.content.MutableContextWrapper
import androidx.credentials.ClearCredentialStateRequest
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import java.security.SecureRandom
import android.util.Base64

object GoogleAuthManager {

    suspend fun signIn(activity: Activity): Result<GoogleAccount> = runCatching {
        val clientId = AuthStore.googleWebClientId(activity)
        require(clientId.isNotBlank()) {
            "Не указан Google Web Client ID. Добавь его в Настройки → Google OAuth."
        }

        val option = GetSignInWithGoogleOption.Builder(
            serverClientId = clientId
        )
            .setNonce(generateNonce())
            .build()

        val request = GetCredentialRequest.Builder()
            .addCredentialOption(option)
            .build()

        val result = CredentialManager.create(activity).getCredential(
            context = MutableContextWrapper(activity),
            request = request
        )

        val custom = result.credential as? CustomCredential
            ?: error("Google не вернул поддерживаемые данные аккаунта")

        require(custom.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
            "Получен неизвестный тип Google credential"
        }

        val credential = GoogleIdTokenCredential.createFrom(custom.data)
        val account = GoogleAccount(
            uniqueId = credential.uniqueId,
            email = credential.email.orEmpty(),
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
