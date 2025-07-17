import unittest
from unittest.mock import patch, Mock
from autodrome.http_client import HttpClient  # Ajusta la ruta según tu proyecto
import requests

class TestHttpClient(unittest.TestCase):

    def setUp(self):
        self.client = HttpClient()

    @patch('requests.get')
    def test_get_success(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {'status': 'ok'}
        mock_get.return_value = mock_response

        result = self.client.get("https://example.com/api")
        self.assertEqual(result, {'status': 'ok'})
        mock_get.assert_called_once()

    @patch('requests.get')
    def test_get_raises_exception(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

        with self.assertRaises(requests.exceptions.RequestException):
            self.client.get("https://example.com/api")

    @patch('requests.get')
    def test_get_binary_success(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        response = self.client.get_binary("https://example.com/image.png")
        self.assertEqual(response, mock_response)
        mock_get.assert_called_once_with(
            "https://example.com/image.png",
            headers=self.client.headers,
            stream=True,
            timeout=10
        )

    @patch('requests.get')
    def test_get_binary_raises_exception(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

        with self.assertRaises(requests.exceptions.RequestException):
            self.client.get_binary("https://example.com/image.png")

if __name__ == '__main__':
    unittest.main()
