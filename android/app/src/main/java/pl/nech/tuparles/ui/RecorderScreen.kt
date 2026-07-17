package pl.nech.tuparles.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import pl.nech.tuparles.data.Note
import pl.nech.tuparles.record.RecorderState
import pl.nech.tuparles.record.RecordingService
import pl.nech.tuparles.util.Format

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecorderScreen(viewModel: RecorderViewModel = hiltViewModel()) {
    val context = LocalContext.current
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    var pendingDelete by remember { mutableStateOf<Note?>(null) }

    // A single toggle: request the mic (and notifications on 33+) on first use.
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { grants ->
        if (grants[Manifest.permission.RECORD_AUDIO] == true) RecordingService.toggle(context)
    }
    val onRecordTap: () -> Unit = {
        val micGranted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        if (micGranted) {
            RecordingService.toggle(context)
        } else {
            val perms = buildList {
                add(Manifest.permission.RECORD_AUDIO)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    add(Manifest.permission.POST_NOTIFICATIONS)
                }
            }
            permissionLauncher.launch(perms.toTypedArray())
        }
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("TuParles") }) },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            RecordControl(state.recorder, onRecordTap)

            if (state.notes.isEmpty()) {
                EmptyState(Modifier.weight(1f))
            } else {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(state.notes, key = { it.id }) { note ->
                        NoteRow(
                            note = note,
                            onShare = { shareNote(context, note) },
                            onDelete = { pendingDelete = note },
                        )
                    }
                }
            }
        }
    }

    pendingDelete?.let { note ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("Supprimer la note ?") },
            text = { Text("${Format.timestamp(note.createdAt)} — ${Format.duration(note.durationS)}. L'audio sera effacé.") },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.delete(note)
                    pendingDelete = null
                }) { Text("Supprimer") }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = null }) { Text("Annuler") }
            },
        )
    }
}

@Composable
private fun RecordControl(recorder: RecorderState, onTap: () -> Unit) {
    val recording = recorder is RecorderState.Recording
    val saving = recorder is RecorderState.Saving
    val elapsed = (recorder as? RecorderState.Recording)?.elapsedMs ?: 0L
    val level = (recorder as? RecorderState.Recording)?.level ?: 0f

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        val buttonColor by animateColorAsState(
            if (recording) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
            label = "recordButtonColor",
        )
        FilledIconButton(
            onClick = onTap,
            enabled = !saving,
            modifier = Modifier.size(96.dp),
        ) {
            Icon(
                imageVector = if (recording) Icons.Filled.Stop else Icons.Filled.Mic,
                contentDescription = if (recording) "Arrêter" else "Enregistrer",
                tint = Color.Unspecified,
                modifier = Modifier.size(44.dp),
            )
        }
        Text(
            text = when {
                recording -> Format.duration(elapsed / 1000f)
                saving -> "enregistrement…"
                else -> "Appuyez pour dicter"
            },
            style = MaterialTheme.typography.titleMedium,
            color = buttonColor,
        )
        if (recording) {
            LinearProgressIndicator(
                progress = { level.coerceIn(0f, 1f) },
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(CircleShape),
            )
        }
    }
}

@Composable
private fun NoteRow(note: Note, onShare: () -> Unit, onDelete: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 16.dp, top = 8.dp, bottom = 8.dp, end = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(Format.timestamp(note.createdAt), style = MaterialTheme.typography.bodyLarge)
                Text(
                    text = note.transcript?.takeIf { it.isNotBlank() } ?: "durée ${Format.duration(note.durationS)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            IconButton(onClick = onShare) {
                Icon(Icons.Filled.Share, contentDescription = "Partager")
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Filled.Delete, contentDescription = "Supprimer")
            }
        }
    }
}

@Composable
private fun EmptyState(modifier: Modifier = Modifier) {
    Box(modifier = modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Text(
            "Aucune note pour l'instant.\nAppuyez sur le micro pour commencer.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
