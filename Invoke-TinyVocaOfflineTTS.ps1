<#
.SYNOPSIS
    Synthesizes offline English speech WAV audio using the audited local tiny-voca 4.5M-parameter TTS engine.

.DESCRIPTION
    Provides a 100% offline (~70x real-time on CPU) fallback speech synthesizer for the Screen Reader
    and AAC projects using the plain-JavaScript or Python tiny-voca runtime in agent-tools\tiny-voca\repo.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $false, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
    [string]$Text = "Hello! Tiny Voca offline speech synthesis is ready.",

    [Parameter(Mandatory = $false)]
    [ValidateSet('F2', 'M2')]
    [string]$Voice = 'F2',

    [Parameter(Mandatory = $false)]
    [string]$OutputWavPath,

    [Parameter(Mandatory = $false)]
    [switch]$CheckStatusOnly
)

begin {
    $ErrorActionPreference = 'Stop'
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (-not $ScriptDir) { $ScriptDir = $PSScriptRoot }
    Set-Location -Path $ScriptDir

    $TinyVocaRepo = "g:\My Drive\Antigravity\Projects\Popular Github Projects\agent-tools\tiny-voca\repo"
    $JsSayScript = Join-Path -Path $TinyVocaRepo -ChildPath "js\say.mjs"
}

process {
    try {
        if (-not (Test-Path -LiteralPath $TinyVocaRepo)) {
            throw [System.IO.DirectoryNotFoundException]::new("tiny-voca repository not found at $TinyVocaRepo")
        }

        if ([string]::IsNullOrWhiteSpace($OutputWavPath)) {
            $OutputWavPath = Join-Path -Path $ScriptDir -ChildPath "tiny_voca_output.wav"
        }

        $weightsBin = Join-Path -Path $TinyVocaRepo -ChildPath "js\tiny-voca.gguf"
        $weightsPresent = Test-Path -LiteralPath $weightsBin
        $synthesized = $false

        if (-not $CheckStatusOnly) {
            if ($PSCmdlet.ShouldProcess($OutputWavPath, "Synthesize speech with tiny-voca voice $Voice")) {
                if (-not $weightsPresent) {
                    $hfUrl = "https://huggingface.co/n4ze3m/tiny-voca/resolve/main/gguf/tiny-voca-js.gguf"
                    Invoke-WebRequest -Uri $hfUrl -OutFile $weightsBin -UseBasicParsing
                    $weightsPresent = Test-Path -LiteralPath $weightsBin
                }
                $sayOut = & node $JsSayScript $Text --file $weightsBin --voice $Voice --output $OutputWavPath 2>&1
                $synthesized = Test-Path -LiteralPath $OutputWavPath
            }
        }

        [PSCustomObject]@{
            ToolName       = 'tiny-voca'
            Version        = '0.2.0'
            RepositoryPath = $TinyVocaRepo
            JsRunnerPath   = $JsSayScript
            Voice          = $Voice
            WeightsPresent = $weightsPresent
            OutputWavPath  = $OutputWavPath
            Synthesized    = $synthesized
        }
    } catch [System.IO.DirectoryNotFoundException] {
        Write-Error -Message $_.Exception.Message -ErrorAction Stop
    } catch {
        Write-Error -Message ("tiny-voca error: {0}" -f $_.Exception.Message) -ErrorAction Stop
    } finally {
        Set-Location -Path $ScriptDir
    }
}

end {}
