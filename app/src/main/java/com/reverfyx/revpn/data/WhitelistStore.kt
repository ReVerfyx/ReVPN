package com.reverfyx.revpn.data

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager

data class LaunchableApp(
    val packageName: String,
    val label: String
)

object WhitelistStore {
    private const val PREFS = "revpn_whitelist"
    private const val KEY_PACKAGES = "packages"

    fun selectedPackages(context: Context): Set<String> =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getStringSet(KEY_PACKAGES, emptySet())
            ?.toSet()
            ?: emptySet()

    fun toggle(context: Context, packageName: String): Set<String> {
        val next = selectedPackages(context).toMutableSet()
        if (!next.add(packageName)) next.remove(packageName)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putStringSet(KEY_PACKAGES, next)
            .apply()
        return next
    }

    fun launchableApps(context: Context): List<LaunchableApp> {
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val flags = if (android.os.Build.VERSION.SDK_INT >= 33) {
            PackageManager.ResolveInfoFlags.of(PackageManager.MATCH_ALL.toLong())
        } else {
            @Suppress("DEPRECATION")
            null
        }

        val resolved = if (android.os.Build.VERSION.SDK_INT >= 33) {
            pm.queryIntentActivities(intent, flags!!)
        } else {
            @Suppress("DEPRECATION")
            pm.queryIntentActivities(intent, PackageManager.MATCH_ALL)
        }

        return resolved
            .mapNotNull { info ->
                val pkg = info.activityInfo?.packageName ?: return@mapNotNull null
                if (pkg == context.packageName) return@mapNotNull null
                LaunchableApp(
                    packageName = pkg,
                    label = info.loadLabel(pm)?.toString()?.trim().orEmpty().ifBlank { pkg }
                )
            }
            .distinctBy { it.packageName }
            .sortedBy { it.label.lowercase() }
    }

    fun launch(context: Context, packageName: String): Boolean {
        val intent = context.packageManager.getLaunchIntentForPackage(packageName) ?: return false
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
        return true
    }
}
