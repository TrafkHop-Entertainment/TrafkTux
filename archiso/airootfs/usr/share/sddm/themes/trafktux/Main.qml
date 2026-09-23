import QtQuick 2.15

// TrafkTux SDDM Theme
// v4 - KORREKTUR des grundlegenden Fehlers aus v3: die Blasen/Pfeile-PNGs
// sind KEINE kleinen, fertig zugeschnittenen Icons - es sind volle
// 1920x1080-Canvases mit dem Inhalt an einer bestimmten Stelle DARIN
// positioniert, genau wie bei GRUB (GrubLayer0-4). Deswegen jetzt:
//
//   1) JEDES Bild (Back/Front/Arrow) wird als volles Vollbild-Image
//      dargestellt (anchors.fill: root, PreserveAspectCrop) - exakt wie
//      Logo/Vignette/Background. Position/Groesse der sichtbaren Blase
//      steckt schon IM Bild selbst, keine QML-Positionierung noetig.
//   2) Fuer Klick-Hotspots, Text-Overlay und Bounce-Transform-Origin
//      werden die tatsaechlichen Content-Positionen der PNGs gemessen
//      (als Anteil der 1920x1080-Canvas) und ueber dieselbe "cover"-
//      Skalierung (max(w/1920,h/1080)) auf Bildschirmkoordinaten
//      umgerechnet - scrX/scrY() unten.
//
// Gemessene Werte (LeftArrow.png, LeftBubbleBack.png, MiddleBubbleFront.png
// tatsaechlich per Python/Alpha-Kanal-Bounding-Box nachgemessen):
//   left-Blase:   center=(0.1341, 0.6185) size=(0.2682, 0.4537)
//   middle-Blase: center=(0.5000, 0.6551) size=(0.2281, 0.4083)
//   left-Pfeil:   center=(0.3529, 0.6657) size=(0.2391, 0.4574)
// right-Blase/-Pfeil sind NICHT direkt gemessen, sondern an der x-Achse
// gespiegelt angenommen (1 - x). Falls das nicht stimmt (asymmetrisches
// Design), bitte Bescheid geben, dann miss ich die echten Dateien nach.

Rectangle {
    id: root

    readonly property rect screenGeometry: screenModel.geometry(screenModel.primary)
    width: screenGeometry.width
    height: screenGeometry.height
    readonly property real s: root.height / 1080

    color: "#23163b"

    // "cover"-Skalierungsfaktor: derselbe Faktor, den PreserveAspectCrop
    // fuer die Vollbild-Images intern verwendet. Damit rechnen wir jede
    // Canvas-Position (Anteil von 1920x1080) auf echte Bildschirm-Pixel um.
    readonly property real canvasScale: Math.max(root.width / 1920, root.height / 1080)
    readonly property real canvasOffX: (root.width - 1920 * canvasScale) / 2
    readonly property real canvasOffY: (root.height - 1080 * canvasScale) / 2
    function scrX(fx) { return canvasOffX + fx * 1920 * canvasScale; }
    function scrY(fy) { return canvasOffY + fy * 1080 * canvasScale; }
    function scrW(fw) { return fw * 1920 * canvasScale; }
    function scrH(fh) { return fh * 1080 * canvasScale; }

    // Layout-Daten aus den tatsaechlichen Dateien gemessen, mit einem
    // haerteren Alpha-Schwellwert (>50%) statt "jedes Alpha>0" - manche
    // Layer (v.a. MiddleBubbleBack) haben einen riesigen, sehr schwachen
    // Glow-Halo drumrum, der die "volle" Bounding Box unnoetig aufblaeht.
    // Mit dem haerteren Schwellwert passen linke/rechte Seite auch exakt
    // symmetrisch zusammen (nachgemessen, nicht mehr nur angenommen).
    readonly property var layout: ({
        left:       { cx: 0.1474, cy: 0.6139, w: 0.0646, h: 0.1130 },
        middle:     { cx: 0.5000, cy: 0.6542, w: 0.2260, h: 0.4065 },
        right:      { cx: 0.8505, cy: 0.6120, w: 0.0625, h: 0.1093 },
        leftArrow:  { cx: 0.3516, cy: 0.6574, w: 0.0271, h: 0.0870 },
        rightArrow: { cx: 0.6484, cy: 0.6574, w: 0.0271, h: 0.0870 }
    })
    // Hitboxen etwas grosszuegiger als die reine Solid-Groesse (leichter
    // zu treffen), aber nicht mehr wild ueberdimensioniert wie vorher.
    readonly property real hitPad: 1.6

    // ── Hintergrund: volle Canvas, "cover" ─────────────────────────
    Image {
        source: "Background.png"
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        z: 0
    }

    // ══════════════════════════════════════════════════════════════
    // Unsichtbares Repeater ueber userModel fuer Index-basierten Zugriff
    // (userModel/sessionModel haben kein .get(), nur Rollen-Properties
    // im Delegate-Kontext).
    // ══════════════════════════════════════════════════════════════
    Item {
        visible: false
        Repeater {
            id: userRepeater
            model: userModel
            delegate: Item {
                property string userName: model.name
                property string displayName: model.realName && model.realName.length > 0 ? model.realName : model.name
            }
        }
    }

    property int currentIndex: userModel.lastIndex >= 0 ? userModel.lastIndex : 0

    function wrapIndex(i) {
        if (userRepeater.count <= 0) return 0;
        return ((i % userRepeater.count) + userRepeater.count) % userRepeater.count;
    }
    readonly property int leftIndex: wrapIndex(currentIndex - 1)
    readonly property int rightIndex: wrapIndex(currentIndex + 1)
    function nameAt(i) { return userRepeater.count > 0 ? userRepeater.itemAt(i).displayName : ""; }
    readonly property string middleName: nameAt(currentIndex)
    readonly property string leftName: nameAt(leftIndex)
    readonly property string rightName: nameAt(rightIndex)

    function switchUser(delta) {
        currentIndex = wrapIndex(currentIndex + delta);
    }

    // ══════════════════════════════════════════════════════════════
    // Linke Blase - Back+Front als Vollbild-Paar, Bounce-Origin auf die
    // gemessene Bubble-Position gesetzt (nicht Canvas-Mitte!).
    // ══════════════════════════════════════════════════════════════
    Item {
        id: leftGroup
        anchors.fill: parent
        z: 1
        transform: Scale {
            id: leftScale
            origin.x: root.scrX(root.layout.left.cx)
            origin.y: root.scrY(root.layout.left.cy)
        }
        function bounce() { leftBounceAnim.restart(); }
        SequentialAnimation {
            id: leftBounceAnim
            ParallelAnimation {
                NumberAnimation { target: leftScale; property: "xScale"; to: 0.85; duration: 80; easing.type: Easing.OutQuad }
                NumberAnimation { target: leftScale; property: "yScale"; to: 0.85; duration: 80; easing.type: Easing.OutQuad }
            }
            ParallelAnimation {
                NumberAnimation { target: leftScale; property: "xScale"; to: 1.0; duration: 220; easing.type: Easing.OutBack; easing.overshoot: 3 }
                NumberAnimation { target: leftScale; property: "yScale"; to: 1.0; duration: 220; easing.type: Easing.OutBack; easing.overshoot: 3 }
            }
        }
        Image { source: "LeftBubbleBack.png"; anchors.fill: parent; fillMode: Image.PreserveAspectCrop }
        Image { source: "LeftBubbleFront.png"; anchors.fill: parent; fillMode: Image.PreserveAspectCrop }
        Text {
            text: root.leftName
            color: "#dcd2ff"
            font.pixelSize: 16 * root.s
            font.bold: true
            width: root.width * 0.12
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            x: root.scrX(root.layout.left.cx) - width / 2
            y: root.scrY(root.layout.left.cy) - height / 2
        }
        MouseArea {
            width: root.scrW(root.layout.left.w) * root.hitPad
            height: root.scrH(root.layout.left.h) * root.hitPad
            x: root.scrX(root.layout.left.cx) - width / 2
            y: root.scrY(root.layout.left.cy) - height / 2
            onClicked: { leftGroup.bounce(); root.switchUser(-1); }
        }
    }

    // ══════════════════════════════════════════════════════════════
    // Rechte Blase - Spiegelbild vom selben Aufbau.
    // ══════════════════════════════════════════════════════════════
    Item {
        id: rightGroup
        anchors.fill: parent
        z: 1
        transform: Scale {
            id: rightScale
            origin.x: root.scrX(root.layout.right.cx)
            origin.y: root.scrY(root.layout.right.cy)
        }
        function bounce() { rightBounceAnim.restart(); }
        SequentialAnimation {
            id: rightBounceAnim
            ParallelAnimation {
                NumberAnimation { target: rightScale; property: "xScale"; to: 0.85; duration: 80; easing.type: Easing.OutQuad }
                NumberAnimation { target: rightScale; property: "yScale"; to: 0.85; duration: 80; easing.type: Easing.OutQuad }
            }
            ParallelAnimation {
                NumberAnimation { target: rightScale; property: "xScale"; to: 1.0; duration: 220; easing.type: Easing.OutBack; easing.overshoot: 3 }
                NumberAnimation { target: rightScale; property: "yScale"; to: 1.0; duration: 220; easing.type: Easing.OutBack; easing.overshoot: 3 }
            }
        }
        Image { source: "RightBubbleBack.png"; anchors.fill: parent; fillMode: Image.PreserveAspectCrop }
        Image { source: "RightBubbleFront.png"; anchors.fill: parent; fillMode: Image.PreserveAspectCrop }
        Text {
            text: root.rightName
            color: "#dcd2ff"
            font.pixelSize: 16 * root.s
            font.bold: true
            width: root.width * 0.12
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            x: root.scrX(root.layout.right.cx) - width / 2
            y: root.scrY(root.layout.right.cy) - height / 2
        }
        MouseArea {
            width: root.scrW(root.layout.right.w) * root.hitPad
            height: root.scrH(root.layout.right.h) * root.hitPad
            x: root.scrX(root.layout.right.cx) - width / 2
            y: root.scrY(root.layout.right.cy) - height / 2
            onClicked: { rightGroup.bounce(); root.switchUser(1); }
        }
    }

    // ══════════════════════════════════════════════════════════════
    // Mittlere Blase (aktueller User) - Bounce auf beiden Achsen.
    // ══════════════════════════════════════════════════════════════
    Item {
        id: middleGroup
        anchors.fill: parent
        z: 1
        transform: Scale {
            id: middleScale
            origin.x: root.scrX(root.layout.middle.cx)
            origin.y: root.scrY(root.layout.middle.cy)
        }
        function bounce() { middleBounceAnim.restart(); }
        SequentialAnimation {
            id: middleBounceAnim
            ParallelAnimation {
                NumberAnimation { target: middleScale; property: "xScale"; to: 0.88; duration: 90; easing.type: Easing.OutQuad }
                NumberAnimation { target: middleScale; property: "yScale"; to: 0.88; duration: 90; easing.type: Easing.OutQuad }
            }
            ParallelAnimation {
                NumberAnimation { target: middleScale; property: "xScale"; to: 1.0; duration: 260; easing.type: Easing.OutBack; easing.overshoot: 3 }
                NumberAnimation { target: middleScale; property: "yScale"; to: 1.0; duration: 260; easing.type: Easing.OutBack; easing.overshoot: 3 }
            }
        }

        Image { source: "MiddleBubbleBack.png"; anchors.fill: parent; fillMode: Image.PreserveAspectCrop }
        Image { source: "MiddleBubbleFront.png"; anchors.fill: parent; fillMode: Image.PreserveAspectCrop }

        // Fake-Glow hinterm Namen (mehrere skalierte, ausblassende Kopien).
        Item {
            x: root.scrX(root.layout.middle.cx) - width / 2
            y: root.scrY(root.layout.middle.cy) - height / 2
            width: root.scrW(root.layout.middle.w) * 0.85
            height: 80 * root.s
            Repeater {
                model: 7
                delegate: Text {
                    text: root.middleName
                    color: "#fff495"
                    opacity: 0.22 - index * 0.028
                    font.pixelSize: 34 * root.s
                    font.bold: true
                    anchors.centerIn: parent
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    transform: Scale {
                        origin.x: width / 2
                        origin.y: height / 2
                        xScale: 1.0 + index * 0.22
                        yScale: 1.0 + index * 0.45
                    }
                }
            }
        }
        Text {
            text: root.middleName
            color: "#fff495"
            font.pixelSize: 34 * root.s
            font.bold: true
            width: root.scrW(root.layout.middle.w) * 0.85
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            x: root.scrX(root.layout.middle.cx) - width / 2
            y: root.scrY(root.layout.middle.cy) - height / 2
        }
    }

    // ══════════════════════════════════════════════════════════════
    // Pfeile - eigene Vollbild-Layer, Klick-Hotspot + Bounce an der
    // gemessenen Pfeilspitzen-Position.
    // ══════════════════════════════════════════════════════════════
    Item {
        id: leftArrowGroup
        anchors.fill: parent
        z: 3
        transform: Scale {
            id: leftArrowScale
            origin.x: root.scrX(root.layout.leftArrow.cx)
            origin.y: root.scrY(root.layout.leftArrow.cy)
        }
        function bounce() { leftArrowBounce.restart(); }
        SequentialAnimation {
            id: leftArrowBounce
            NumberAnimation { target: leftArrowScale; property: "xScale"; to: 0.75; duration: 70; easing.type: Easing.OutQuad }
            NumberAnimation { target: leftArrowScale; property: "xScale"; to: 1.0; duration: 200; easing.type: Easing.OutBack; easing.overshoot: 4 }
        }
        Image { source: "LeftArrow.png"; anchors.fill: parent; fillMode: Image.PreserveAspectCrop }
        MouseArea {
            width: root.scrW(root.layout.leftArrow.w) * root.hitPad
            height: root.scrH(root.layout.leftArrow.h) * root.hitPad
            x: root.scrX(root.layout.leftArrow.cx) - width / 2
            y: root.scrY(root.layout.leftArrow.cy) - height / 2
            onClicked: { leftArrowGroup.bounce(); root.switchUser(-1); middleGroup.bounce(); }
        }
    }

    Item {
        id: rightArrowGroup
        anchors.fill: parent
        z: 3
        transform: Scale {
            id: rightArrowScale
            origin.x: root.scrX(root.layout.rightArrow.cx)
            origin.y: root.scrY(root.layout.rightArrow.cy)
        }
        function bounce() { rightArrowBounce.restart(); }
        SequentialAnimation {
            id: rightArrowBounce
            NumberAnimation { target: rightArrowScale; property: "xScale"; to: 0.75; duration: 70; easing.type: Easing.OutQuad }
            NumberAnimation { target: rightArrowScale; property: "xScale"; to: 1.0; duration: 200; easing.type: Easing.OutBack; easing.overshoot: 4 }
        }
        Image { source: "RightArrow.png"; anchors.fill: parent; fillMode: Image.PreserveAspectCrop }
        MouseArea {
            width: root.scrW(root.layout.rightArrow.w) * root.hitPad
            height: root.scrH(root.layout.rightArrow.h) * root.hitPad
            x: root.scrX(root.layout.rightArrow.cx) - width / 2
            y: root.scrY(root.layout.rightArrow.cy) - height / 2
            onClicked: { rightArrowGroup.bounce(); root.switchUser(1); middleGroup.bounce(); }
        }
    }

    // ══════════════════════════════════════════════════════════════
    // Reboot/Shutdown - PLATZHALTER: einfacher Text statt Icon (wie
    // gewuenscht ausgelassen, bis eigene Assets existieren).
    // ══════════════════════════════════════════════════════════════
    Text {
        text: "Neustart"
        color: "#f6f3d5"
        font.pixelSize: 16 * root.s
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 30 * root.s
        z: 3
        MouseArea { anchors.fill: parent; anchors.margins: -10 * root.s; onClicked: sddm.reboot() }
    }
    Text {
        text: "Herunterfahren"
        color: "#f6f3d5"
        font.pixelSize: 16 * root.s
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 30 * root.s
        z: 3
        MouseArea { anchors.fill: parent; anchors.margins: -10 * root.s; onClicked: sddm.powerOff() }
    }

    // ── Vignette + Logo: volle Canvas, "cover", vorne ──────────────
    Image { source: "Vignette.png"; anchors.fill: parent; fillMode: Image.PreserveAspectCrop; z: 4 }

    // Logo-Rotationszentrum jetzt exakt aus Logo.png gemessen (Alpha>50%):
    // center=(0.5000, 0.1819), size=(0.4260, 0.1935).
    Image {
        id: logoImage
        source: "Logo.png"
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        z: 5
        transform: [
            Rotation {
                id: logoRotation
                origin.x: root.scrX(0.5)
                origin.y: root.scrY(0.1819)
                angle: 0
            },
            Scale {
                id: logoBounceScale
                origin.x: root.scrX(0.5)
                origin.y: root.scrY(0.1819)
                xScale: 1.0
                yScale: 1.0
            }
        ]
        SequentialAnimation {
            id: logoSpin
            ParallelAnimation {
                NumberAnimation { target: logoRotation; property: "angle"; from: 0; to: 360; duration: 700; easing.type: Easing.InOutQuad }
                SequentialAnimation {
                    NumberAnimation { target: logoBounceScale; properties: "xScale,yScale"; to: 0.85; duration: 140; easing.type: Easing.OutQuad }
                    NumberAnimation { target: logoBounceScale; properties: "xScale,yScale"; to: 1.0; duration: 350; easing.type: Easing.OutBack; easing.overshoot: 3 }
                }
            }
        }
        MouseArea {
            width: root.scrW(0.426) * root.hitPad
            height: root.scrH(0.1935) * root.hitPad
            x: root.scrX(0.5) - width / 2
            y: root.scrY(0.1819) - height / 2
            onClicked: { logoRotation.angle = 0; logoSpin.restart(); }
        }
    }

    // ── Passwort: komplett unsichtbar ───────────────────────────────
    TextInput {
        id: passwordInput
        visible: false
        focus: true
        echoMode: TextInput.Password
        onAccepted: root.doLogin()
    }
    MouseArea {
        anchors.fill: parent
        z: -1
        onClicked: passwordInput.forceActiveFocus()
    }
    function doLogin() {
        var uname = root.nameAt(root.currentIndex);
        if (uname.length === 0) return;
        sddm.login(uname, passwordInput.text, 0);
    }
    Connections {
        target: sddm
        function onLoginFailed() {
            errorText.text = "Falsches Passwort";
            errorFadeAnim.restart();
            passwordInput.text = "";
            passwordInput.forceActiveFocus();
        }
    }

    // ── Fehlermeldung: rot, unten, ueber allem ─────────────────────
    Text {
        id: errorText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 30 * root.s
        color: "#ff5555"
        font.pixelSize: 16 * root.s
        font.bold: true
        text: ""
        opacity: 0
        z: 10
        SequentialAnimation {
            id: errorFadeAnim
            NumberAnimation { target: errorText; property: "opacity"; to: 1.0; duration: 150 }
            PauseAnimation { duration: 3000 }
            NumberAnimation { target: errorText; property: "opacity"; to: 0.0; duration: 400 }
        }
    }

    Component.onCompleted: passwordInput.forceActiveFocus();
}
