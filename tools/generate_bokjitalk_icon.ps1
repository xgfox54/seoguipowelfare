[CmdletBinding()]
param(
    [string]$SourcePath
)

Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$assetsDir = Join-Path $root 'assets'
$webDir = Join-Path $root 'web'
New-Item -ItemType Directory -Force -Path $assetsDir, $webDir | Out-Null

if ([string]::IsNullOrWhiteSpace($SourcePath)) {
    $SourcePath = Join-Path $assetsDir 'bokjitalk-source.png'
}
if (-not (Test-Path -LiteralPath $SourcePath)) {
    throw "아이콘 원본 PNG를 찾을 수 없습니다: $SourcePath"
}

function New-RoundedRectPath {
    param(
        [float]$X,
        [float]$Y,
        [float]$Width,
        [float]$Height,
        [float]$Radius
    )
    $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $diameter = $Radius * 2
    $path.AddArc($X, $Y, $diameter, $diameter, 180, 90)
    $path.AddArc($X + $Width - $diameter, $Y, $diameter, $diameter, 270, 90)
    $path.AddArc($X + $Width - $diameter, $Y + $Height - $diameter, $diameter, $diameter, 0, 90)
    $path.AddArc($X, $Y + $Height - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    return $path
}

function New-LogoBitmap {
    param([int]$Size = 512)

    $bitmap = [System.Drawing.Bitmap]::new($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.Clear([System.Drawing.Color]::Transparent)

    $scale = $Size / 512.0
    $outer = New-RoundedRectPath (16 * $scale) (16 * $scale) (480 * $scale) (480 * $scale) (92 * $scale)
    $gradient = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
        [System.Drawing.PointF]::new(32 * $scale, 24 * $scale),
        [System.Drawing.PointF]::new(474 * $scale, 488 * $scale),
        [System.Drawing.Color]::FromArgb(255, 34, 197, 255),
        [System.Drawing.Color]::FromArgb(255, 0, 87, 214)
    )
    $graphics.FillPath($gradient, $outer)

    $highlightPath = New-RoundedRectPath (28 * $scale) (28 * $scale) (456 * $scale) (210 * $scale) (76 * $scale)
    $highlightBrush = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
        [System.Drawing.PointF]::new(40 * $scale, 28 * $scale),
        [System.Drawing.PointF]::new(40 * $scale, 238 * $scale),
        [System.Drawing.Color]::FromArgb(95, 255, 255, 255),
        [System.Drawing.Color]::FromArgb(0, 255, 255, 255)
    )
    $graphics.FillPath($highlightBrush, $highlightPath)

    $waveBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(35, 255, 255, 255))
    $wavePath = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $wavePath.StartFigure()
    $wavePath.AddBezier(20 * $scale, 350 * $scale, 160 * $scale, 292 * $scale, 265 * $scale, 430 * $scale, 492 * $scale, 332 * $scale)
    $wavePath.AddLine(492 * $scale, 332 * $scale, 492 * $scale, 492 * $scale)
    $wavePath.AddLine(492 * $scale, 492 * $scale, 20 * $scale, 492 * $scale)
    $wavePath.CloseFigure()
    $graphics.FillPath($waveBrush, $wavePath)

    $fontFamily = 'Malgun Gothic'
    try {
        $fontWhite = [System.Drawing.Font]::new($fontFamily, 120 * $scale, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
        $fontYellow = [System.Drawing.Font]::new($fontFamily, 120 * $scale, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    } catch {
        $fontWhite = [System.Drawing.Font]::new('Arial', 120 * $scale, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
        $fontYellow = [System.Drawing.Font]::new('Arial', 120 * $scale, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
    }

    $whiteBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
    $yellowBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 255, 222, 42))
    $shadowBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(72, 0, 49, 145))
    $format = [System.Drawing.StringFormat]::new([System.Drawing.StringFormat]::GenericTypographic)
    $format.FormatFlags = $format.FormatFlags -bor [System.Drawing.StringFormatFlags]::MeasureTrailingSpaces

    $textY = 154 * $scale
    $whiteText = ([char]0xBCF5).ToString() + ([char]0xC9C0).ToString()
    $yellowText = ([char]0xD1A1).ToString()
    $whiteSize = $graphics.MeasureString($whiteText, $fontWhite, 1000, $format)
    $yellowSize = $graphics.MeasureString($yellowText, $fontYellow, 1000, $format)
    $totalWidth = $whiteSize.Width + $yellowSize.Width - (12 * $scale)
    $startX = ($Size - $totalWidth) / 2

    $shadowOffset = 5 * $scale
    $graphics.DrawString($whiteText, $fontWhite, $shadowBrush, [System.Drawing.PointF]::new($startX + $shadowOffset, $textY + $shadowOffset), $format)
    $graphics.DrawString($yellowText, $fontYellow, $shadowBrush, [System.Drawing.PointF]::new($startX + $whiteSize.Width - (12 * $scale) + $shadowOffset, $textY + $shadowOffset), $format)
    $graphics.DrawString($whiteText, $fontWhite, $whiteBrush, [System.Drawing.PointF]::new($startX, $textY), $format)
    $graphics.DrawString($yellowText, $fontYellow, $yellowBrush, [System.Drawing.PointF]::new($startX + $whiteSize.Width - (12 * $scale), $textY), $format)

    $bubblePen = [System.Drawing.Pen]::new([System.Drawing.Color]::White, 13 * $scale)
    $bubblePen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $bubblePen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $bubblePath = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $bubblePath.StartFigure()
    $bubblePath.AddBezier(78 * $scale, 325 * $scale, 175 * $scale, 337 * $scale, 310 * $scale, 336 * $scale, 404 * $scale, 315 * $scale)
    $bubblePath.AddBezier(404 * $scale, 315 * $scale, 382 * $scale, 343 * $scale, 363 * $scale, 360 * $scale, 342 * $scale, 381 * $scale)
    $bubblePath.AddBezier(342 * $scale, 381 * $scale, 323 * $scale, 356 * $scale, 305 * $scale, 343 * $scale, 278 * $scale, 336 * $scale)
    $graphics.DrawPath($bubblePen, $bubblePath)

    $rayPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255, 255, 222, 42), 15 * $scale)
    $rayPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $rayPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $graphics.DrawLine($rayPen, 398 * $scale, 112 * $scale, 406 * $scale, 72 * $scale)
    $graphics.DrawLine($rayPen, 432 * $scale, 127 * $scale, 460 * $scale, 98 * $scale)
    $graphics.DrawLine($rayPen, 446 * $scale, 160 * $scale, 482 * $scale, 151 * $scale)

    $graphics.Dispose()
    $outer.Dispose()
    $gradient.Dispose()
    $highlightPath.Dispose()
    $highlightBrush.Dispose()
    $waveBrush.Dispose()
    $wavePath.Dispose()
    $fontWhite.Dispose()
    $fontYellow.Dispose()
    $whiteBrush.Dispose()
    $yellowBrush.Dispose()
    $shadowBrush.Dispose()
    $format.Dispose()
    $bubblePen.Dispose()
    $bubblePath.Dispose()
    $rayPen.Dispose()
    return $bitmap
}

function Save-MultiSizeIco {
    param(
        [System.Drawing.Bitmap]$Master,
        [string]$Path
    )
    $sizes = @(16, 24, 32, 48, 64, 128, 256)
    $images = @()
    foreach ($size in $sizes) {
        $resized = [System.Drawing.Bitmap]::new($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $g = [System.Drawing.Graphics]::FromImage($resized)
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $g.Clear([System.Drawing.Color]::Transparent)
        $g.DrawImage($Master, 0, 0, $size, $size)
        $g.Dispose()
        $ms = [System.IO.MemoryStream]::new()
        $resized.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $resized.Dispose()
        $images += ,@($size, $ms.ToArray())
        $ms.Dispose()
    }

    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
    $writer = [System.IO.BinaryWriter]::new($stream)
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$images.Count)
    $offset = 6 + (16 * $images.Count)
    foreach ($entry in $images) {
        $size = [int]$entry[0]
        $bytes = [byte[]]$entry[1]
        if ($size -eq 256) {
            $dimensionByte = [byte]0
        } else {
            $dimensionByte = [byte]$size
        }
        $writer.Write($dimensionByte)
        $writer.Write($dimensionByte)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$bytes.Length)
        $writer.Write([uint32]$offset)
        $offset += $bytes.Length
    }
    foreach ($entry in $images) {
        $writer.Write([byte[]]$entry[1])
    }
    $writer.Dispose()
    $stream.Dispose()
}

function New-SourceBitmap {
    param(
        [string]$Path,
        [int]$Size = 512
    )

    $source = [System.Drawing.Image]::FromFile($Path)
    try {
        $bitmap = [System.Drawing.Bitmap]::new($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
            $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
            $graphics.Clear([System.Drawing.Color]::Transparent)
            $graphics.DrawImage(
                $source,
                [System.Drawing.Rectangle]::new(0, 0, $Size, $Size),
                0,
                0,
                $source.Width,
                $source.Height,
                [System.Drawing.GraphicsUnit]::Pixel
            )
        } finally {
            $graphics.Dispose()
        }
        return $bitmap
    } finally {
        $source.Dispose()
    }
}

$master = New-SourceBitmap -Path $SourcePath -Size 512
$assetPng = Join-Path $assetsDir 'bokjitalk.png'
$webPng = Join-Path $webDir 'bokjitalk.png'
$assetIco = Join-Path $assetsDir 'bokjitalk.ico'
$webIco = Join-Path $webDir 'bokjitalk.ico'
$master.Save($assetPng, [System.Drawing.Imaging.ImageFormat]::Png)
$master.Save($webPng, [System.Drawing.Imaging.ImageFormat]::Png)
Save-MultiSizeIco $master $assetIco
Copy-Item -Force $assetIco $webIco

$cornerPixels = @(
    $master.GetPixel(0, 0),
    $master.GetPixel(511, 0),
    $master.GetPixel(0, 511),
    $master.GetPixel(511, 511)
)
$master.Dispose()

Write-Output "PNG=$webPng"
Write-Output "ICO=$assetIco"
Write-Output ("CORNER_ALPHA=" + (($cornerPixels | ForEach-Object { $_.A }) -join ','))
Write-Output ("ICO_BYTES=" + (Get-Item $assetIco).Length)
