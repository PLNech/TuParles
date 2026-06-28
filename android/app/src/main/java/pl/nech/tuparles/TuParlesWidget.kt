package pl.nech.tuparles

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews

/**
 * The smart widget: a one-tap dictate surface on the home screen. Tapping the box
 * toggles DictationService for the TARGET_WIDGET sink — start/stop recording without
 * opening the app. The service pushes live state back here (recording meter →
 * decoding → ✅ copied N car.), and on completion drops the text on the clipboard
 * with a notification, so the widget is genuinely useful from anywhere. It never
 * holds state itself; it's a thin face over the same compute backbone every surface
 * shares.
 */
class TuParlesWidget : AppWidgetProvider() {

    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        // Reflect whatever the service is currently doing (idle if it's stopped).
        render(context, DictationService.state.value)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == ACTION_WIDGET_TOGGLE) {
            DictationService.toggle(context, DictationService.TARGET_WIDGET)
        }
    }

    companion object {
        const val ACTION_WIDGET_TOGGLE = "pl.nech.tuparles.WIDGET_TOGGLE"

        private fun faceFor(s: DictationState): Pair<String, String> = when (s) {
            is DictationState.Recording -> "■ Stop" to "🔴 ${"%.1f".format(s.elapsedMs / 1000f)}s"
            is DictationState.Decoding -> "⏳" to "décodage…"
            else -> "🎙 TuParles" to "Toucher pour dicter"
        }

        /** Push the current dictation state to every placed widget instance. */
        fun render(context: Context, s: DictationState) {
            val manager = AppWidgetManager.getInstance(context) ?: return
            val ids = manager.getAppWidgetIds(ComponentName(context, TuParlesWidget::class.java))
            if (ids.isEmpty()) return
            val (title, status) = faceFor(s)
            val views = RemoteViews(context.packageName, R.layout.widget_tuparles).apply {
                setTextViewText(R.id.widget_title, title)
                setTextViewText(R.id.widget_status, status)
                setOnClickPendingIntent(R.id.widget_root, togglePendingIntent(context))
            }
            manager.updateAppWidget(ids, views)
        }

        private fun togglePendingIntent(context: Context): PendingIntent {
            val intent = Intent(context, TuParlesWidget::class.java).setAction(ACTION_WIDGET_TOGGLE)
            return PendingIntent.getBroadcast(
                context, 0, intent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
        }
    }
}
