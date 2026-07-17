package pl.nech.tuparles.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.clickable
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
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import pl.nech.tuparles.data.TranscriptState
import pl.nech.tuparles.record.RecorderState
import pl.nech.tuparles.record.RecordingService
import pl.nech.tuparles.util.Format
import pl.nech.tuparles.util.TranscriptSnippet

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecorderScreen(viewModel: RecorderViewModel = hiltViewModel()) {
    val context = LocalContext.current
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    // The field echoes the raw query synchronously; only search execution is debounced (#41).
    val queryText by viewModel.queryText.collectAsStateWithLifecycle()

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

            // The search field appears once there's anything to search (or a query in
            // flight); with no notes ever recorded it stays out of the way.
            if (state.notes.isNotEmpty() || queryText.isNotEmpty()) {
                SearchField(queryText, viewModel::onQueryChange)
            }
            if (state.searching && state.untranscribedHidden > 0) {
                UntranscribedHint(state.untranscribedHidden)
            }

            when {
                // Nothing recorded yet.
                queryText.isEmpty() && state.notes.isEmpty() -> EmptyState(Modifier.weight(1f))
                // A search that matched nothing.
                state.notes.isEmpty() -> NoMatchState(queryText, Modifier.weight(1f))
                else -> LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(state.notes, key = { it.id }) { note ->
                        NoteRow(
                            note = note,
                            query = if (state.searching) state.query else "",
                            onShareAudio = { shareNote(context, note) },
                            onShareText = { shareText(context, note) },
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
private fun SearchField(query: String, onQueryChange: (String) -> Unit) {
    OutlinedTextField(
        value = query,
        onValueChange = onQueryChange,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp),
        singleLine = true,
        placeholder = { Text("Chercher dans les transcriptions") },
        leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
        trailingIcon = {
            if (query.isNotEmpty()) {
                IconButton(onClick = { onQueryChange("") }) {
                    Icon(Icons.Filled.Close, contentDescription = "Effacer la recherche")
                }
            }
        },
    )
}

/** Why some notes vanished during a search: they have no transcript to match against. */
@Composable
private fun UntranscribedHint(count: Int) {
    val label = if (count == 1) {
        "1 note sans transcript, non cherchable"
    } else {
        "$count notes sans transcript, non cherchables"
    }
    Text(
        text = label,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 2.dp),
    )
}

@Composable
private fun NoMatchState(query: String, modifier: Modifier = Modifier) {
    Box(modifier = modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Text(
            "Aucun résultat pour « ${query.trim()} ».\nEssayez d'autres mots — try other words.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun NoteRow(
    note: Note,
    query: String,
    onShareAudio: () -> Unit,
    onShareText: () -> Unit,
    onDelete: () -> Unit,
) {
    val hasTranscript = !note.transcript.isNullOrBlank()
    var expanded by remember(note.id) { mutableStateOf(false) }

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .animateContentSize()
            // Tapping a note with a transcript expands/collapses the full text.
            .clickable(enabled = hasTranscript) { expanded = !expanded },
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 16.dp, top = 8.dp, bottom = 8.dp, end = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(Format.timestamp(note.createdAt), style = MaterialTheme.typography.bodyLarge)
                Text(
                    text = subtitle(note, hasTranscript, query, expanded),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = if (expanded) Int.MAX_VALUE else 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            ShareButton(hasTranscript, onShareAudio, onShareText)
            IconButton(onClick = onDelete) {
                Icon(Icons.Filled.Delete, contentDescription = "Supprimer")
            }
        }
    }
}

/**
 * The row's second line: while collapsed inside a search it shows a snippet centred on
 * the match; otherwise the transcript when decoded, a live hint while decoding, else
 * duration. Expanding always reveals the full transcript.
 */
private fun subtitle(note: Note, hasTranscript: Boolean, query: String, expanded: Boolean): String = when {
    hasTranscript && query.isNotBlank() && !expanded -> TranscriptSnippet.around(note.transcript!!, query)
    hasTranscript -> note.transcript!!.trim()
    note.transcriptState.inFlight -> "transcription…"
    note.transcriptState == TranscriptState.FAILED -> "transcription échouée — durée ${Format.duration(note.durationS)}"
    else -> "durée ${Format.duration(note.durationS)}"
}

/** One share affordance: audio-only until a transcript exists, then a menu (audio / texte). */
@Composable
private fun ShareButton(hasTranscript: Boolean, onShareAudio: () -> Unit, onShareText: () -> Unit) {
    if (!hasTranscript) {
        IconButton(onClick = onShareAudio) {
            Icon(Icons.Filled.Share, contentDescription = "Partager l'audio")
        }
        return
    }
    var menuOpen by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { menuOpen = true }) {
            Icon(Icons.Filled.Share, contentDescription = "Partager")
        }
        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
            DropdownMenuItem(
                text = { Text("Partager le texte") },
                onClick = { menuOpen = false; onShareText() },
            )
            DropdownMenuItem(
                text = { Text("Partager l'audio") },
                onClick = { menuOpen = false; onShareAudio() },
            )
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
