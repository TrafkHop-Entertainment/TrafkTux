import QtQuick 2.15

// TrafkTux SDDM Theme
// Selbe Optik wie GRUB/Plymouth: Hintergrund #23163b -> #1a0d34, Logo
// oben + Trennstrich. Nutzerauswahl als horizontal scrollbare Blasen-
// liste (mittig, etwas oberhalb der Bildschirmmitte), Passwortfeld als
// gestreckte Blase (etwas unterhalb der Mitte), kleine Blasen-Icons für
// Session-Wechsel/Neustart/Herunterfahren unten rechts.
//
// Kein .get()/ComboBox-Kram verwendet - SDDMs userModel/sessionModel
// sind C++-Modelle ohne .get()-Methode, daher werden Werte ausschließ-
// lich über Rollen-Properties in Delegates gelesen (zuverlässig, egal
// welche Qt-Version).

Rectangle {
    id: root
    width: 1920
    height: 1080

    gradient: Gradient {
        GradientStop { position: 0.0; color: "#23163b" }
        GradientStop { position: 1.0; color: "#1a0d34" }
    }

    // ── Logo ─────────────────────────────────────────────────
    Image {
        id: logo
        source: "logo.png"
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.height * 0.02
    }

    // ── Trennstrich (wie GRUB/Plymouth) ─────────────────────
    Rectangle {
        id: divider
        width: parent.width
        height: 2
        color: "#fff495"
        opacity: 0.55
        y: logo.y + logo.height + 15
    }

    // ── Nutzerauswahl: horizontal scrollbare Blasenliste ────
    ListView {
        id: userList
        orientation: ListView.Horizontal
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -100
        width: Math.min(parent.width * 0.8, count * 380)
        height: 350
        spacing: 30
        model: userModel
        currentIndex: userModel.lastIndex >= 0 ? userModel.lastIndex : 0
        highlightMoveDuration: 150
        focus: true
        preferredHighlightBegin: width / 2 - 175
        preferredHighlightEnd: width / 2 + 175
        highlightRangeMode: ListView.ApplyRange

        delegate: Item {
            id: userDelegate
            width: 350
            height: 350
            property bool isCurrent: ListView.isCurrentItem
            property string userName: model.name
            property string displayName: model.realName && model.realName.length > 0 ? model.realName : model.name

            Image {
                id: bubbleImg
                // Blase bleibt IMMER die normale, nicht-leuchtende Version -
                // nur der Text des aktiven Users leuchtet, nicht die Blase.
                source: "bubble_user_normal.png"
                width: 350
                height: 350
                smooth: true
                mipmap: true
                anchors.centerIn: parent
            }

            // Fake-Glow fuer den aktiven User: mehrere zunehmend skalierte,
            // dabei ausblassende Text-Kopien uebereinander (kein
            // GraphicsEffects-Modul noetig, das haette wieder eine eigene
            // Import-Versionsfalle wie bei "import QtQuick" ohne Version
            // sein koennen). Simuliert einen echten, mit Abstand
            // schwaecher werdenden Glow statt der alten 8-Punkt-Streuung.
            // Explizites Scale-Transform mit festem origin (statt der
            // eingebauten "scale"-Property) und mehr Y- als X-Stretch,
            // damit der Glow nicht schief nach unten wegdriftet und
            // vertikal laenglicher wirkt.
            Item {
                anchors.centerIn: bubbleImg
                width: bubbleImg.width * 0.8
                height: 70
                visible: userDelegate.isCurrent

                Repeater {
                    model: 7
                    delegate: Text {
                        text: userDelegate.displayName
                        color: "#fff495"
                        opacity: 0.22 - index * 0.028
                        font.pixelSize: 34
                        font.bold: true
                        anchors.centerIn: parent
                        width: parent.width
                        height: parent.height
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
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
                text: userDelegate.displayName
                color: userDelegate.isCurrent ? "#fff495" : "#dcd2ff"
                font.pixelSize: userDelegate.isCurrent ? 34 : 20
                font.bold: true
                anchors.centerIn: bubbleImg
                width: bubbleImg.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
            }
            MouseArea {
                anchors.fill: bubbleImg
                onClicked: userList.currentIndex = index
            }
        }
    }

    // ── Passwortfeld: gestreckte Blase ───────────────────────
    Item {
        id: pwArea
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: 285
        width: 420
        height: 90

        Image {
            id: pwBubble
            source: "bubble_pw_selected.png"
            anchors.fill: parent
            fillMode: Image.Stretch
            smooth: true
            mipmap: true
        }

        TextInput {
            id: passwordInput
            focus: true
            anchors.centerIn: parent
            width: parent.width * 0.7
            color: "#f6f3d5"
            font.pixelSize: 20
            echoMode: TextInput.Password
            horizontalAlignment: TextInput.AlignHCenter
            clip: true

            Text {
                text: "Passwort"
                color: "#9c81cf"
                anchors.fill: parent
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                visible: passwordInput.text.length === 0 && !passwordInput.activeFocus
            }

            onAccepted: root.doLogin()
        }

        MouseArea {
            anchors.fill: parent
            onClicked: passwordInput.forceActiveFocus()
        }
    }

    Text {
        id: errorText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: pwArea.bottom
        anchors.topMargin: 12
        color: "#ff5555"
        font.pixelSize: 14
        text: ""
        visible: text.length > 0
    }

    function doLogin() {
        var uname = userList.currentItem ? userList.currentItem.userName : ""
        if (uname.length === 0) return
        sddm.login(uname, passwordInput.text, sessionList.currentItem ? sessionList.currentIndex : 0)
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            errorText.text = "Falsches Passwort"
            passwordInput.text = ""
            passwordInput.forceActiveFocus()
        }
    }

    // Unsichtbare ListView nur zum zuverlaessigen Auslesen von
    // sessionModel-Werten ueber Rollen-Properties (kein .get() noetig).
    ListView {
        id: sessionList
        visible: false
        model: sessionModel
        currentIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0
        delegate: Item {
            property string sessionName: model.name
        }
    }

    // ── Session-Blase: unten rechts ─────────────────────────
    Item {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 30
        width: 56
        height: 56
        Image { source: "bubble_btn_normal.png"; anchors.fill: parent; smooth: true; mipmap: true }
        Text {
            anchors.centerIn: parent
            text: sessionList.currentItem ? sessionList.currentItem.sessionName.substring(0, 2).toUpperCase() : ""
            color: "#f6f3d5"
            font.pixelSize: 13
            font.bold: true
        }
        MouseArea {
            anchors.fill: parent
            onClicked: sessionList.currentIndex = (sessionList.currentIndex + 1) % Math.max(sessionModel.rowCount(), 1)
        }
    }

    // ── Reboot-Blase: unten links ───────────────────────────
    Item {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 30
        width: 56
        height: 56
        Image { source: "bubble_btn_normal.png"; anchors.fill: parent; smooth: true; mipmap: true }
        Text { anchors.centerIn: parent; text: "\u27F3"; color: "#f6f3d5"; font.pixelSize: 24 }
        MouseArea { anchors.fill: parent; onClicked: sddm.reboot() }
    }

    Component.onCompleted: {
        passwordInput.forceActiveFocus()
    }
}
