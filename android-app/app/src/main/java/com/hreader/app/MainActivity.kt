package com.hreader.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.webkit.*
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView

    companion object {
        private const val READER_DIR_NAME = "Reader"
        private const val PERMISSION_REQUEST_CODE = 100
    }

    private val readerDir: File
        get() = File(Environment.getExternalStorageDirectory(), READER_DIR_NAME)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        WindowCompat.setDecorFitsSystemWindows(window, false)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        setupWebView()

        if (hasStoragePermission()) {
            loadLibrary()
        } else {
            requestStoragePermission()
        }
    }

    // ========================================
    // PERMISSIONS
    // ========================================

    private fun hasStoragePermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            ContextCompat.checkSelfPermission(
                this, Manifest.permission.READ_EXTERNAL_STORAGE
            ) == PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(
                this, Manifest.permission.WRITE_EXTERNAL_STORAGE
            ) == PackageManager.PERMISSION_GRANTED
        }
    }

    private fun requestStoragePermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION).apply {
                    data = Uri.parse("package:$packageName")
                }
                startActivityForResult(intent, PERMISSION_REQUEST_CODE)
            } catch (e: Exception) {
                val intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
                startActivityForResult(intent, PERMISSION_REQUEST_CODE)
            }
        } else {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(
                    Manifest.permission.READ_EXTERNAL_STORAGE,
                    Manifest.permission.WRITE_EXTERNAL_STORAGE
                ),
                PERMISSION_REQUEST_CODE
            )
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == PERMISSION_REQUEST_CODE) {
            if (grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
                loadLibrary()
            } else {
                Toast.makeText(this, "Storage permission required to access books", Toast.LENGTH_LONG).show()
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == PERMISSION_REQUEST_CODE) {
            if (hasStoragePermission()) {
                loadLibrary()
            } else {
                Toast.makeText(this, "Storage permission required to access books", Toast.LENGTH_LONG).show()
            }
        }
    }

    // ========================================
    // WEBVIEW SETUP
    // ========================================

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            allowFileAccessFromFileURLs = true
            allowUniversalAccessFromFileURLs = true
            mediaPlaybackRequiresUserGesture = false
            cacheMode = WebSettings.LOAD_DEFAULT
            builtInZoomControls = false
            displayZoomControls = false
            useWideViewPort = true
            loadWithOverviewMode = true
        }

        webView.addJavascriptInterface(HReaderBridge(), "HReaderBridge")

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                hideSystemUI()
            }

            override fun shouldInterceptRequest(
                view: WebView?,
                request: WebResourceRequest?
            ): WebResourceResponse? {
                // Allow file:// URIs for images and audio to pass through
                return super.shouldInterceptRequest(view, request)
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onJsAlert(
                view: WebView?,
                url: String?,
                message: String?,
                result: JsResult?
            ): Boolean {
                Toast.makeText(this@MainActivity, message, Toast.LENGTH_SHORT).show()
                result?.confirm()
                return true
            }

            override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                consoleMessage?.let {
                    android.util.Log.d("HReaderJS", "${it.message()} [${it.sourceId()}:${it.lineNumber()}]")
                }
                return true
            }
        }
    }

    private fun loadLibrary() {
        // Ensure Reader directory exists
        val dir = readerDir
        if (!dir.exists()) {
            dir.mkdirs()
        }
        webView.loadUrl("file:///android_asset/library.html")
    }

    private fun hideSystemUI() {
        val windowInsetsController = WindowCompat.getInsetsController(window, window.decorView)
        windowInsetsController.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        windowInsetsController.hide(WindowInsetsCompat.Type.systemBars())
    }

    override fun onKeyDown(keyCode: Int, event: android.view.KeyEvent?): Boolean {
        if (keyCode == android.view.KeyEvent.KEYCODE_BACK) {
            // If webview can go back (reader -> library), go back
            if (webView.canGoBack()) {
                webView.goBack()
                return true
            }
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onResume() {
        super.onResume()
        webView.onResume()
        hideSystemUI()
    }

    override fun onPause() {
        super.onPause()
        webView.onPause()
    }

    // ========================================
    // JAVASCRIPT BRIDGE
    // ========================================

    inner class HReaderBridge {

        /**
         * Scan Reader dir for *_data/book.json folders.
         * Returns JSON array: [{id, title, author, cover_url, has_audio}, ...]
         */
        @JavascriptInterface
        fun getBookList(): String {
            val books = JSONArray()
            val dir = readerDir
            if (!dir.exists() || !dir.isDirectory) return books.toString()

            val bookDirs = dir.listFiles { f -> f.isDirectory && f.name.endsWith("_data") }
                ?.sortedBy { it.name }
                ?: return books.toString()

            for (bookDir in bookDirs) {
                val bookJson = File(bookDir, "book.json")
                if (!bookJson.exists()) continue

                try {
                    val data = JSONObject(bookJson.readText())
                    val metadata = data.optJSONObject("metadata")
                    val bookId = bookDir.name.removeSuffix("_data")

                    val entry = JSONObject().apply {
                        put("id", bookId)
                        put("title", metadata?.optString("title", bookId) ?: bookId)
                        val authors = metadata?.optJSONArray("authors")
                        put("author", if (authors != null && authors.length() > 0) authors.getString(0) else "")

                        // Cover image
                        val coverImage = data.optString("cover_image", "")
                        if (coverImage.isNotEmpty()) {
                            put("cover_url", "file://${bookDir.absolutePath}/$coverImage")
                        } else {
                            put("cover_url", JSONObject.NULL)
                        }

                        // Check for audio files
                        val audioDir = File(bookDir, "audio")
                        val hasAudio = audioDir.exists() && audioDir.isDirectory &&
                            (audioDir.listFiles()?.any {
                                it.extension.lowercase() in listOf("mp3", "m4b", "m4a", "ogg", "opus", "flac", "wav")
                            } ?: false)
                        put("has_audio", hasAudio)
                    }
                    books.put(entry)
                } catch (e: Exception) {
                    android.util.Log.e("HReaderBridge", "Error reading book: ${bookDir.name}", e)
                }
            }
            return books.toString()
        }

        /**
         * Return full book.json content for a given bookId.
         */
        @JavascriptInterface
        fun getBookData(bookId: String): String {
            val bookJson = File(readerDir, "${bookId}_data/book.json")
            return if (bookJson.exists()) bookJson.readText() else "{}"
        }

        /**
         * Return the filesystem path for the book's data directory.
         * Used by JS to construct file:// URIs for images.
         */
        @JavascriptInterface
        fun getBookBasePath(bookId: String): String {
            return File(readerDir, "${bookId}_data").absolutePath
        }

        // ---- HIGHLIGHTS ----

        @JavascriptInterface
        fun getHighlights(bookId: String, chapterIndex: Int): String {
            val file = File(readerDir, "${bookId}_data/highlights.json")
            if (!file.exists()) return """{"highlights":[]}"""

            return try {
                val data = JSONObject(file.readText())
                val chapterKey = chapterIndex.toString()
                val chapterHighlights = data.optJSONArray(chapterKey) ?: JSONArray()
                val result = JSONObject()
                result.put("highlights", chapterHighlights)
                result.toString()
            } catch (e: Exception) {
                android.util.Log.e("HReaderBridge", "Error reading highlights", e)
                """{"highlights":[]}"""
            }
        }

        @JavascriptInterface
        fun saveHighlight(bookId: String, chapterIndex: Int, highlightJson: String) {
            val file = File(readerDir, "${bookId}_data/highlights.json")
            try {
                val data = if (file.exists()) JSONObject(file.readText()) else JSONObject()
                val chapterKey = chapterIndex.toString()
                val chapterHighlights = data.optJSONArray(chapterKey) ?: JSONArray()

                val newHighlight = JSONObject(highlightJson)
                chapterHighlights.put(newHighlight)
                data.put(chapterKey, chapterHighlights)

                file.writeText(data.toString(2))
            } catch (e: Exception) {
                android.util.Log.e("HReaderBridge", "Error saving highlight", e)
            }
        }

        @JavascriptInterface
        fun deleteHighlight(bookId: String, chapterIndex: Int, highlightId: String) {
            val file = File(readerDir, "${bookId}_data/highlights.json")
            if (!file.exists()) return

            try {
                val data = JSONObject(file.readText())
                val chapterKey = chapterIndex.toString()
                val chapterHighlights = data.optJSONArray(chapterKey) ?: return

                val filtered = JSONArray()
                for (i in 0 until chapterHighlights.length()) {
                    val h = chapterHighlights.getJSONObject(i)
                    if (h.optString("id") != highlightId) {
                        filtered.put(h)
                    }
                }
                data.put(chapterKey, filtered)
                file.writeText(data.toString(2))
            } catch (e: Exception) {
                android.util.Log.e("HReaderBridge", "Error deleting highlight", e)
            }
        }

        // ---- READING PROGRESS ----

        @JavascriptInterface
        fun getProgress(bookId: String): String {
            val file = File(readerDir, "${bookId}_data/reading_progress.json")
            return if (file.exists()) file.readText() else "{}"
        }

        @JavascriptInterface
        fun saveProgress(bookId: String, progressJson: String) {
            val file = File(readerDir, "${bookId}_data/reading_progress.json")
            try {
                // Pretty-print for readability / easier syncthing diffs
                val data = JSONObject(progressJson)
                file.writeText(data.toString(2))
            } catch (e: Exception) {
                android.util.Log.e("HReaderBridge", "Error saving progress", e)
            }
        }

        // ---- AUDIO ----

        @JavascriptInterface
        fun getAudioMetadata(bookId: String): String {
            val audioDir = File(readerDir, "${bookId}_data/audio")
            val result = JSONObject()

            if (!audioDir.exists() || !audioDir.isDirectory) {
                result.put("available", false)
                return result.toString()
            }

            val audioExtensions = listOf("mp3", "m4b", "m4a", "ogg", "opus", "flac", "wav")
            val audioFiles = audioDir.listFiles { f ->
                f.isFile && f.extension.lowercase() in audioExtensions
            }?.sortedBy { it.name } ?: emptyList()

            if (audioFiles.isEmpty()) {
                result.put("available", false)
                return result.toString()
            }

            result.put("available", true)
            result.put("is_multi_file", audioFiles.size > 1)

            val chapters = JSONArray()
            audioFiles.forEachIndexed { index, file ->
                val chapter = JSONObject().apply {
                    put("index", index)
                    put("filename", file.name)
                    put("title", file.nameWithoutExtension)
                }
                chapters.put(chapter)
            }
            result.put("chapters", chapters)

            return result.toString()
        }

        @JavascriptInterface
        fun getAudioPosition(bookId: String): String {
            val file = File(readerDir, "${bookId}_data/audiobook_state.json")
            return if (file.exists()) file.readText() else "{}"
        }

        @JavascriptInterface
        fun saveAudioPosition(bookId: String, positionJson: String) {
            val file = File(readerDir, "${bookId}_data/audiobook_state.json")
            try {
                val data = JSONObject(positionJson)
                file.writeText(data.toString(2))
            } catch (e: Exception) {
                android.util.Log.e("HReaderBridge", "Error saving audio position", e)
            }
        }

        @JavascriptInterface
        fun getAudioFileUri(bookId: String, index: Int): String {
            val audioDir = File(readerDir, "${bookId}_data/audio")
            if (!audioDir.exists()) return ""

            val audioExtensions = listOf("mp3", "m4b", "m4a", "ogg", "opus", "flac", "wav")
            val audioFiles = audioDir.listFiles { f ->
                f.isFile && f.extension.lowercase() in audioExtensions
            }?.sortedBy { it.name } ?: return ""

            return if (index in audioFiles.indices) {
                "file://${audioFiles[index].absolutePath}"
            } else ""
        }
    }
}
