package com.hreader.app

import android.annotation.SuppressLint
import android.content.SharedPreferences
import android.os.Bundle
import android.view.KeyEvent
import android.view.View
import android.webkit.*
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

class MainActivity : AppCompatActivity() {
    
    private lateinit var webView: WebView
    private lateinit var setupLayout: LinearLayout
    private lateinit var serverUrlInput: EditText
    private lateinit var connectButton: Button
    private lateinit var errorText: TextView
    private lateinit var prefs: SharedPreferences
    
    companion object {
        private const val PREFS_NAME = "hreader_prefs"
        private const val KEY_SERVER_URL = "server_url"
        private const val DEFAULT_PORT = "8123"
    }
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Enable edge-to-edge display
        WindowCompat.setDecorFitsSystemWindows(window, false)
        
        setContentView(R.layout.activity_main)
        
        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        
        webView = findViewById(R.id.webView)
        setupLayout = findViewById(R.id.setupLayout)
        serverUrlInput = findViewById(R.id.serverUrlInput)
        connectButton = findViewById(R.id.connectButton)
        errorText = findViewById(R.id.errorText)
        
        setupWebView()
        
        val savedUrl = prefs.getString(KEY_SERVER_URL, null)
        if (savedUrl != null) {
            // Try to connect to saved server
            connectToServer(savedUrl)
        } else {
            // Show setup screen
            showSetupScreen()
        }
        
        connectButton.setOnClickListener {
            val input = serverUrlInput.text.toString().trim()
            if (input.isNotEmpty()) {
                val url = normalizeUrl(input)
                connectToServer(url)
            } else {
                errorText.text = "Please enter your laptop's IP address"
                errorText.visibility = View.VISIBLE
            }
        }
    }
    
    private fun normalizeUrl(input: String): String {
        var url = input
        
        // Add http:// if no protocol
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://$url"
        }
        
        // Add port if not present
        if (!url.contains(":8123") && !url.contains(":80") && !url.matches(Regex(".*:\\d+.*"))) {
            url = "$url:$DEFAULT_PORT"
        }
        
        return url
    }
    
    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            mediaPlaybackRequiresUserGesture = false
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            cacheMode = WebSettings.LOAD_DEFAULT
            
            // Enable zooming
            builtInZoomControls = true
            displayZoomControls = false
            
            // Better rendering
            useWideViewPort = true
            loadWithOverviewMode = true
        }
        
        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                // Page loaded successfully - hide setup, show webview
                if (url != null && !url.startsWith("about:")) {
                    showWebView()
                    // Save the working URL
                    val baseUrl = url.substringBefore("/", url).let {
                        if (it.contains("://")) url.split("/").take(3).joinToString("/")
                        else it
                    }
                    prefs.edit().putString(KEY_SERVER_URL, baseUrl).apply()
                }
            }
            
            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                super.onReceivedError(view, request, error)
                // Only handle main frame errors
                if (request?.isForMainFrame == true) {
                    showSetupScreen()
                    errorText.text = "Could not connect to server. Check if:\n" +
                            "1. Your laptop server is running\n" +
                            "2. Both devices are on the same WiFi\n" +
                            "3. The IP address is correct"
                    errorText.visibility = View.VISIBLE
                }
            }
        }
        
        // Handle JavaScript alerts
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
        }
    }
    
    private fun connectToServer(url: String) {
        errorText.visibility = View.GONE
        webView.loadUrl(url)
    }
    
    private fun showSetupScreen() {
        setupLayout.visibility = View.VISIBLE
        webView.visibility = View.GONE
        
        // Pre-fill with saved URL if available
        val savedUrl = prefs.getString(KEY_SERVER_URL, null)
        if (savedUrl != null) {
            serverUrlInput.setText(savedUrl.removePrefix("http://").removePrefix("https://"))
        }
    }
    
    private fun showWebView() {
        setupLayout.visibility = View.GONE
        webView.visibility = View.VISIBLE
        hideSystemUI()
    }
    
    private fun hideSystemUI() {
        val windowInsetsController = WindowCompat.getInsetsController(window, window.decorView)
        windowInsetsController.systemBarsBehavior = 
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        windowInsetsController.hide(WindowInsetsCompat.Type.systemBars())
    }
    
    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        // Handle back button - go back in WebView history
        if (keyCode == KeyEvent.KEYCODE_BACK && webView.canGoBack()) {
            webView.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }
    
    override fun onResume() {
        super.onResume()
        webView.onResume()
        if (webView.visibility == View.VISIBLE) {
            hideSystemUI()
        }
    }
    
    override fun onPause() {
        super.onPause()
        webView.onPause()
    }
}
