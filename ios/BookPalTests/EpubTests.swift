import Testing

@testable import BookPal

struct HTMLBlokkenTests {
    @Test func test_paragraphs_become_separate_blocks() {
        let blokken = HTMLBlokken.splits("<p>Een</p><p>Twee</p>")
        #expect(blokken == ["<p>Een</p>", "<p>Twee</p>"])
    }

    @Test func test_headings_and_images_are_their_own_block() {
        let blokken = HTMLBlokken.splits("<h1>Kop</h1><img src=\"a.jpg\"/><p>Tekst</p>")
        #expect(blokken.count == 3)
        #expect(blokken[0] == "<h1>Kop</h1>")
        #expect(blokken[1].hasPrefix("<img"))
    }

    @Test func test_loose_text_between_blocks_is_kept_as_a_paragraph() {
        // Zou dit wegvallen, dan verdwijnt er tekst uit het boek zonder dat
        // iemand het merkt — het ergste wat een lezer kan doen.
        let blokken = HTMLBlokken.splits("<p>Een</p>los stukje<p>Twee</p>")
        #expect(blokken.count == 3)
        #expect(blokken[1].contains("los stukje"))
    }

    @Test func test_whitespace_between_blocks_does_not_become_an_empty_block() {
        let blokken = HTMLBlokken.splits("<p>Een</p>\n  \n<p>Twee</p>")
        #expect(blokken == ["<p>Een</p>", "<p>Twee</p>"])
    }

    @Test func test_html_without_any_block_still_yields_something() {
        #expect(HTMLBlokken.splits("kale tekst") == ["<p>kale tekst</p>"])
    }

    @Test func test_an_empty_chapter_falls_back_to_the_input() {
        #expect(HTMLBlokken.splits("") == [""])
    }
}

struct EpubParserTests {
    @Test func test_a_relative_image_path_resolves_against_its_chapter() {
        // "../Images/p1.jpg" vanuit "OEBPS/Text" hoort "OEBPS/Images/p1.jpg" te
        // worden; anders vindt hij het plaatje niet in het archief.
        #expect(
            EpubParser.normaliseer(pad: "../Images/p1.jpg", vanuit: "OEBPS/Text")
                == "OEBPS/Images/p1.jpg"
        )
    }

    @Test func test_a_path_next_to_the_chapter_keeps_its_folder() {
        #expect(EpubParser.normaliseer(pad: "p1.jpg", vanuit: "OEBPS/Text") == "OEBPS/Text/p1.jpg")
    }

    @Test func test_a_path_at_the_root_has_no_folder() {
        #expect(EpubParser.normaliseer(pad: "p1.jpg", vanuit: "") == "p1.jpg")
    }

    @Test func test_the_spine_gives_the_reading_order() {
        let opf = """
        <spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine>
        """
        #expect(EpubParser.spineVolgorde(opf) == ["c1", "c2"])
    }

    @Test func test_the_manifest_maps_ids_to_files() {
        let opf = """
        <manifest><item id="c1" href="Text/een.xhtml" media-type="application/xhtml+xml"/></manifest>
        """
        #expect(EpubParser.manifestItems(opf)["c1"] == "Text/een.xhtml")
    }

    @Test func test_the_title_comes_out_of_the_metadata() {
        #expect(EpubParser.tussenTags("<dc:title>Down to Earth</dc:title>", tag: "dc:title")
            == "Down to Earth")
    }

    @Test func test_stripping_html_leaves_readable_text() {
        let kaal = EpubParser.striptHTML("<p>Hallo <b>daar</b>&nbsp;&amp; tot ziens</p>")
        #expect(kaal == "Hallo daar & tot ziens")
    }

    @Test func test_a_script_block_does_not_end_up_in_the_text() {
        let kaal = EpubParser.striptHTML("<p>Tekst</p><script>var x = 1;</script>")
        #expect(!kaal.contains("var x"))
    }
}
