package pl.nech.tuparles.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import dagger.hilt.android.AndroidEntryPoint
import pl.nech.tuparles.ui.theme.TuParlesTheme

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            TuParlesTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    AppRoot()
                }
            }
        }
    }
}

private enum class Route { Recorder, Models }

/**
 * Minimal two-screen navigation (recorder ⇄ Réglages/Modèles) held in saveable state —
 * no nav-library dependency for a single settings surface. System back returns to the
 * recorder from Réglages.
 */
@Composable
private fun AppRoot() {
    var route by rememberSaveable { mutableStateOf(Route.Recorder) }
    when (route) {
        Route.Recorder -> RecorderScreen(onOpenSettings = { route = Route.Models })
        Route.Models -> {
            BackHandler { route = Route.Recorder }
            ModelsScreen(onBack = { route = Route.Recorder })
        }
    }
}
